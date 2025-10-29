############################################################################################################################################
# HTML Tracker
#
# When HTML is received in chunks, it may be incomplete (e.g., a <div> tag opened but not closed).
# This class helps track such incomplete HTML and separates valid from incomplete parts.
#
# Maintainer: Urs Utzinger
############################################################################################################################################

import logging  
import re
from html.parser import HTMLParser

class IncompleteHTMLTracker(HTMLParser):
    """
    A streaming HTML parser that detects incomplete HTML.
    Returns:
      - `valid_html`: Fully completed HTML that can be safely displayed.
      - `incomplete_html`: Remaining unprocessed HTML that needs more data.
    """

    def __init__(self):
        super().__init__()
        self.tag_stack = {}                                                    # Dictionary to track open tags {tag_name: count}
        self.incomplete_html_buffer = ""                                       # Store leftover HTML for next chunk
        self.valid_html_buffer = ""                                            # Buffer for confirmed valid HTML

        # Precompile regex patterns for efficiency
        self.tag_start_pattern = re.compile(r"<([a-zA-Z0-9]+)(\s[^<>]*)?>")    # Matches opening tags with optional attributes
        self.tag_end_pattern = re.compile(r"</([a-zA-Z0-9]+)>")                # Matches closing tags

        self.self_closing_tags = {"br", "img", "hr", "input", "meta", "link"}  # Tags that don't require closing

    def handle_starttag(self, tag, attrs) -> None:
        """Track opening tags, unless they are self-closing."""
        if tag not in self.self_closing_tags:
            self.tag_stack[tag] = self.tag_stack.get(tag, 0) + 1               # Increment count
            # logging.debug(f"Opening tag detected: <{tag}> (Total open: {self.tag_stack[tag]})")

    def handle_endtag(self, tag) -> None:
        """Track closing tags and remove from stack when matched."""
        if tag in self.tag_stack:
            self.tag_stack[tag] -= 1                                           # Decrement count
            # logging.debug(f"Closing tag detected: </{tag}> (Remaining open: {self.tag_stack[tag]})")
            if self.tag_stack[tag] == 0:
                del self.tag_stack[tag]                                        # Remove fully closed tag

    def detect_incomplete_html(self, html: str) -> None:
        """
        Processes incoming HTML and separates:
        - `valid_html`: Fully closed and valid HTML content.
        - `incomplete_html`: Content waiting for more data to be completed.
        """
        # logging.debug(f"Received HTML chunk:\n{html}")

        # Append new HTML data to any previously incomplete content
        self.incomplete_html_buffer += html  
        self.valid_html_buffer = ""                                            # Reset valid buffer

        # Try parsing the entire buffer
        try:
            self.feed(self.incomplete_html_buffer)

            if not self.tag_stack:
                # If all tags are closed, the buffer is fully valid
                self.valid_html_buffer = self.incomplete_html_buffer
                self.incomplete_html_buffer = ""                               # Reset after processing
                # logging.debug(f"All tags closed. Valid HTML:\n{self.valid_html_buffer}")
                return self.valid_html_buffer, ""
        except Exception:
            # logging.error(f"HTML Parsing Error: {e}")  # Log parsing errors
            pass

        # Detect where last fully valid HTML ends
        last_valid_position = self._find_last_complete_tag(self.incomplete_html_buffer)

        # Separate valid vs. incomplete parts
        self.valid_html_buffer = self.incomplete_html_buffer[:last_valid_position]
        self.incomplete_html_buffer = self.incomplete_html_buffer[last_valid_position:]

        # logging.debug(f"Valid HTML Extracted:\n{self.valid_html_buffer}")
        # logging.debug(f"Incomplete HTML Stored:\n{self.incomplete_html_buffer}")

        return self.valid_html_buffer, self.incomplete_html_buffer

    def _find_last_complete_tag(self, html: str) -> None:
        """
        Finds the last fully completed tag position in the string.
        Ensures that incomplete start tags (like <p class="...) are not included in valid HTML.
        """
        logging.debug("Scanning for last fully closed tag...")
        last_valid_pos = 0
        open_tags = {}

        # Scan the HTML chunk for opening tags
        for match in self.tag_start_pattern.finditer(html):
            tag_name = match.group(1)
            tag_pos = match.start()

            if tag_name in self.self_closing_tags:
                continue                                                       # Ignore self-closing tags

            open_tags[tag_name] = open_tags.get(tag_name, 0) + 1               # Increment count
            # logging.debug(f"Unmatched opening tag: <{tag_name}> at position {tag_pos}")

        # Scan the HTML chunk for closing tags
        for match in self.tag_end_pattern.finditer(html):
            tag_name = match.group(1)
            tag_pos = match.end()

            if tag_name in open_tags:
                open_tags[tag_name] -= 1
                # logging.debug(f"Matched closing tag: </{tag_name}> at position {tag_pos}")
                if open_tags[tag_name] == 0:
                    del open_tags[tag_name]

            # If no unmatched open tags, update last valid position
            if not open_tags:
                last_valid_pos = tag_pos

        # logging.debug(f"Last valid tag found at position {last_valid_pos}")
        return last_valid_pos
