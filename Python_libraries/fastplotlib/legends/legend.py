from functools import partial
from collections import OrderedDict
from typing import Iterable, Optional

import numpy as np
import pygfx
import inspect
from math import isclose

try:
    from ..utils.enums import RenderQueue
except ImportError:
    pass
from ..graphics import Graphic
from ..graphics.features import GraphicFeatureEvent
from ..graphics import LineGraphic, ScatterGraphic, ImageGraphic
from ..utils import mesh_masks

ROW_SPACING = 20 # Vertical spacing between rows in pixels
COL_SPACING = 10 # Horizontal gap between columns in pixels
FONT_PIX    = 16 # Font pixel size
LINE_LENGTH =  8 # Length of the line in the legend
PADDING     =  2 # Padding around legend panel

HAS_LINE_SCREEN_SPACE  = "screen_space" in inspect.signature(pygfx.Line.__init__).parameters
HAS_GROUP_SCREEN_SPACE = "screen_space" in inspect.signature(pygfx.Group.__init__).parameters
HAS_TEXT_SCREEN_SPACE  = hasattr(pygfx, "Text") and \
    ("screen_space" in inspect.signature(pygfx.Text.__init__).parameters)

class LegendItem:
    def __init__(
        self,
        label: str,
        color: pygfx.Color,
    ):
        """

        Parameters
        ----------
        label: str
            The label for the legend item

        color: pygfx.Color
            The color for the legend item
        """
        self._label = label
        self._color = color

    @property
    def color(self) -> pygfx.Color:
        return self._color

    @color.setter
    def color(self, c: pygfx.Color):
        self._color = c

class LineLegendItem(LegendItem):
    def __init__(
        self, 
        parent, 
        graphic: LineGraphic, 
        label: str,
        position: tuple[int, int],
        label_color=(0.0, 0.0, 0.0, 1.0)
    ):
        """

        Parameters
        ----------
        graphic: LineGraphic

        label: str
            The label for the legend item

        label_color: default (0.0, 0.0, 0.0, 1.0) for black
            The color of the label text

        position: [x, y]
            The position of the legend item in the legend
        """

        # Determine label
        if label is None:
            if getattr(graphic, "name", None):
                label = graphic.name
            else:
                raise ValueError(
                    "Must specify `label` or Graphic must have a `name` to auto-use as the label"
                )

        self._parent = parent

        label_color = pygfx.Color(label_color)
        self._label_color = label_color

        # Extract (single) line color supporting uniform or per-vertex
        col_feature = graphic.colors
        if hasattr(col_feature, "value"):
            vals = col_feature.value
        else:
            vals = np.array([[col_feature.r, col_feature.g, col_feature.b, col_feature.a]], dtype=float)
        unique = np.unique(vals, axis=0).astype(np.float32)
        if unique.shape[0] > 1:
            raise ValueError("Use colorbars for multi-colored lines, not legends")

        line_color = pygfx.Color(unique.ravel())
        super().__init__(label, line_color)

        graphic.colors.add_event_handler(self._update_color)

        material = pygfx.LineMaterial

        # construct Line WorldObject

        line_positions = np.array([[0.0, 0.0, 0.0], [LINE_LENGTH, 0.0, 0.0]], dtype=np.float32)
        line_geometry = pygfx.Geometry(positions=line_positions)

        # Legend Line

        try:
            # pygfx >=0.13.0
            line_kw = {
                "geometry": line_geometry,
                "material": material(
                    alpha_mode="blend",
                    render_queue=RenderQueue.overlay,
                    thickness=8,
                    thickness_space="screen",
                    color=self._color,
                    depth_write=False,
                    depth_test=False,
                )
            }
            if HAS_LINE_SCREEN_SPACE:
                line_kw["screen_space"] = True
            self._line_world_object = pygfx.Line(**line_kw)

        except Exception:
            # pygfx 0.12.0
            line_kw = {
                "geometry": line_geometry,
                "material": material(
                    thickness=8,
                    thickness_space="screen",
                    color=self._color,
                    depth_test=False,
                ),
            }
            if HAS_LINE_SCREEN_SPACE:
                line_kw["screen_space"] = True
            self._line_world_object = pygfx.Line(**line_kw)

        # Legend Label
        try: 
            # pygfx 0.13.0
            text_kw = {
                "text": str(label),
                "font_size": FONT_PIX,
                "anchor": "middle-left",
                "material": pygfx.TextMaterial(
                    alpha_mode="blend",
                    render_queue=RenderQueue.overlay,
                    color=label_color,
                    outline_color=label_color,
                    outline_thickness=0,
                    depth_write=False,
                    depth_test=False,
                ),
            }
            if HAS_TEXT_SCREEN_SPACE:
                text_kw["screen_space"] = True
            self._label_world_object = pygfx.Text(**text_kw)
        except Exception:
            # pygfx 0.12.0
            text_kw = {
                "text": str(label),
                "font_size": FONT_PIX,
                "anchor": "middle-left",
                "material": pygfx.TextMaterial(
                    aa=True,
                    color=label_color,
                    outline_color=label_color,
                    outline_thickness=0,
                    depth_test=False,
                ),
            }
            if HAS_TEXT_SCREEN_SPACE:
                text_kw["screen_space"] = True
            self._label_world_object = pygfx.Text(**text_kw)

        group_kw = {}
        if HAS_GROUP_SCREEN_SPACE:
            group_kw["screen_space"] = True
        self.world_object = pygfx.Group(**group_kw)

        self.world_object.add(self._line_world_object, self._label_world_object)

        self.world_object.world.x = position[0]
        self.world_object.world.y = position[1]
        self.world_object.world.z = 2

        # place the text relative to the legend-item group so row offsets apply
        if hasattr(self._label_world_object, "local"):
            self._label_world_object.local.x = LINE_LENGTH + 4.0
            self._label_world_object.local.y = 0.0
        else:
            # older pygfx builds
            self._label_world_object.position.set_x(LINE_LENGTH + 4.0)
            self._label_world_object.position.set_y(0.0)
        
        self.world_object.add_event_handler(
            partial(self._highlight_graphic, graphic), "click"
        )

    def _update_color(self, ev: GraphicFeatureEvent):
        raw = np.asarray(ev.info["value"], dtype=np.float32)
        unique = np.unique(raw, axis=0)
        if unique.shape[0] > 1:
            raise ValueError(
                "LegendError: LineGraphic colors no longer appropriate for legend"
            )

        color = pygfx.Color(unique.ravel())
        self._color = color
        self._line_world_object.material.color = color
        
    def _highlight_graphic(self, graphic: Graphic, _ev):
        col_feature = graphic.colors
        if hasattr(col_feature, "value"):
            raw = np.asarray(col_feature.value, dtype=np.float32)
        else:  # single color feature
            raw = np.array([[col_feature.r, col_feature.g, col_feature.b, col_feature.a]], dtype=np.float32)

        current_color = pygfx.Color(np.unique(raw, axis=0).ravel())
        highlight = self._parent.highlight_color

        if current_color == highlight:
            # toggle back to the stored line color
            graphic.colors = self._color.rgba
        else:
            # remember the original color, then switch to highlight
            self._color = current_color
            graphic.colors = highlight.rgba

    def set_label_font_size(self, size: float) -> None:
        """Safely apply a font size to the underlying text graphic."""
        label_obj = getattr(self, "_label_world_object", None)
        if label_obj is None:
            label_obj = getattr(getattr(self, "label", None), "text_graphic", None)
        if label_obj is not None:
            label_obj.size = size

    def set_label_color(self, col) -> None:
        """Apply a label color using pygfx.Color for consistency."""
        col = pygfx.Color(col)
        label_obj = getattr(self, "_label_world_object", None)
        if label_obj is None:
            label_obj = getattr(getattr(self, "label", None), "text_graphic", None)
        if label_obj is not None:
            label_obj.color = col
            if hasattr(label_obj, "material") and hasattr(label_obj.material, "outline_color"):
                label_obj.material.color = col
                label_obj.material.outline_color = col

    @property
    def label(self) -> str:
        return self._label

    @label.setter
    def label(self, text: str):
        self._parent._check_label_unique(text)
        self._label = text
        lw = self._label_world_object
        geom = getattr(lw, "geometry", None)
        if geom is not None and hasattr(geom, "set_text"):
            geom.set_text(text)
        elif hasattr(lw, "text"):
            lw.text = text

    # Per-item label color
    @property
    def label_color(self):
        label_obj = getattr(self, "_label_world_object", None)
        if label_obj is None:
            label_obj = getattr(getattr(self, "label", None), "text_graphic", None)
        if label_obj is not None:
            return label_obj.color
        return None

    @label_color.setter
    def label_color(self, value):
        self.set_label_color(value)

class Legend(Graphic):
    def __init__(
        self,
        plot_area,
        background_color: str | tuple | np.ndarray = (0.1, 0.1, 0.1, 1.0),
        highlight_color:  str | tuple | np.ndarray = "w",
        label_color:      str | tuple | np.ndarray = (0.0, 0.0, 0.0, 1.0),
        max_rows: int = 10,
        *args,
        **kwargs,
    ):
        """

        Parameters
        ----------
        plot_area: Union[Plot, Subplot, Dock]
            plot area to put the legend in

        background_color: Union[str, tuple, np.ndarray], default (0.1, 0.1, 0.1, 1.0)
            highlight color

        highlight_color: Union[str, tuple, np.ndarray], default "w"
            highlight color

        label_color: Union[str, tuple, np.ndarray], default (0.0, 0.0, 0.0, 1.0)
            label color

        max_rows: int, default 10
            maximum number of rows allowed in the legend

        """
        self._graphics: list[Graphic] = list()

        # hex id of Graphic, i.e. graphic._fpl_address are the keys
        self._items: OrderedDict[str, LegendItem] = OrderedDict()

        super().__init__(*args, **kwargs)

        bg_color   = pygfx.Color(background_color)
        hi_color   = pygfx.Color(highlight_color)
        label_col  = pygfx.Color(label_color)
        mesh_color = bg_color

        self._legend_items_group = pygfx.Group()

        try:  # pygfx ≥0.13
            self._mesh = pygfx.Mesh(
                geometry=pygfx.box_geometry(50, 10, 1),
                material=pygfx.MeshBasicMaterial(
                    alpha_mode="blend",
                    render_queue=RenderQueue.overlay,
                    color=mesh_color,
                    wireframe_thickness=10,
                    depth_write=False,
                    depth_test=False,
                ),
            )
        except Exception:
            self._mesh = pygfx.Mesh(
                geometry=pygfx.box_geometry(50, 10, 1),
                material=pygfx.MeshBasicMaterial(
                    color=mesh_color,
                    wireframe_thickness=10,
                ),
            )

        group = pygfx.Group()
        group.add(self._mesh)
        group.add(self._legend_items_group)
        self._set_world_object(group)
        self._mesh.render_order = -1

        self._plot_area = plot_area
        dock_has_resize = hasattr(self._plot_area, "resize")
        if dock_has_resize and isinstance(getattr(self._plot_area, "size", None), (tuple, list)):
            if min(self._plot_area.size) < 1:
                self._plot_area.resize((100, 60))
        self._plot_area.add_graphic(self)

        self.default_label_color = label_color
        self.highlight_color     = highlight_color
        self.background_color    = background_color

        # TODO: refactor with "moveable graphic" base class once that's done
        self._mesh.add_event_handler(self._pointer_down, "pointer_down")
        self._plot_area.renderer.add_event_handler(self._pointer_move, "pointer_move")
        self._plot_area.renderer.add_event_handler(self._pointer_up, "pointer_up")

        self._last_position = None
        self._initial_controller_state = self._plot_area.controller.enabled

        self._max_rows    = max_rows
        self._row_counter = 0
        self._col_counter = 0
        self._col_offsets: list[float] = [0.0]
        self._row_spacing = ROW_SPACING
        self._col_spacing = COL_SPACING

    def _check_label_unique(self, label):
        for legend_item in self._items.values():
            if legend_item.label == label:
                raise ValueError(
                    f"You have passed the label '{label}' which is already used for another legend item. "
                    f"All labels within a legend must be unique."
                )

    def add_graphic(
        self, 
        graphic: Graphic, 
        label: str = None, 
        label_color: str | tuple | np.ndarray | pygfx.Color | None = None,
    ):
        """
        Add a graphic to the legend.

        Parameters
        ----------
        graphic: Graphic
            The graphic to add.

        label: str, optional
            The label for the graphic.

        label_color: Union[str, tuple, np.ndarray], optional
            The color of the label.
        """
        if graphic in self._graphics:
            raise KeyError(
                f"Graphic already exists in legend with label: '{self._items[graphic._fpl_address].label}'"
            )

        self._check_label_unique(label)

        # Prepare column and row indices and positions
        col_idx = self._col_counter
        row_idx = self._row_counter

        col_spacing = self._col_spacing
        row_spacing = self._row_spacing

        if row_idx >= self._max_rows:
            # Start new column
            col_idx += 1
            # Obtain last column's items
            prev_items = list(self._items.values())[-self._max_rows :]
            # Compute column width
            max_width = 0.0
            for item in prev_items:
                bbox = item.world_object.get_world_bounding_box()
                w, *_ = np.ptp(bbox, axis=0)
                max_width = max(max_width, w)
            new_offset = self._col_offsets[-1] + max_width + col_spacing
            self._col_offsets.append(new_offset)
            x_pos = new_offset
            y_pos = 0.0
            row_idx = 0            
        else:
            x_pos = self._col_offsets[col_idx]
            y_pos = -row_idx * row_spacing
        row_idx += 1

        if isinstance(graphic, LineGraphic):
            legend_item = LineLegendItem(
                self,
                graphic,
                label,
                position=(x_pos, y_pos),
                label_color=label_color or self.default_label_color,
            )
            legend_item.set_label_font_size(FONT_PIX)
        else:
            raise ValueError("Legend only supported for LineGraphic for now.")

        self._legend_items_group.add(legend_item.world_object)
        self._reset_mesh_dims()

        self._graphics.append(graphic)
        self._items[graphic._fpl_address] = legend_item

        graphic.add_event_handler(partial(self.remove_graphic, graphic), "deleted")

        self._col_counter = col_idx
        self._row_counter = row_idx

    def _reset_mesh_dims(self):
        bbox = self._legend_items_group.get_world_bounding_box() # bounding box of all legend items
        if bbox is None:
            return

        width, height, _ = np.ptp(bbox, axis=0)
        if width == 0 or height == 0:
            return

        pos = self._mesh.geometry.positions.data
        # mesh origin is top left and y increases downwards and x increases rightwards
        pos[mesh_masks.x_left]   =        - PADDING
        pos[mesh_masks.x_right]  = width  + PADDING
        pos[mesh_masks.y_top]    =        - PADDING
        pos[mesh_masks.y_bottom] = height + PADDING
        self._mesh.geometry.positions.update_range(0, pos.shape[0])

    def update_using_camera(self):
        """
        Update the legend position and scale using the camera.

        Legend is in a dock, not on a plot or on a Subplot.
        """

        # Panel bounding box
        bbox = self._legend_items_group.get_world_bounding_box() # bounding box of all legend items
        if bbox is None:
            return
        panel_w, panel_h, _ = np.ptp(bbox, axis=0)
        if panel_w <= 0 or panel_h <= 0:
            return
        panel_center = np.mean(bbox, axis=0)

        # Camera bounding box
        dock = self._plot_area
        dock.camera.set_state({
            "width": panel_w,
            "height": panel_h,
            "position": (panel_center[0], panel_center[1], 1.0),   # z>0 so data at z=0 is in front
            "maintain_aspect": False,                # optional; set True if you want locked aspect
        })

        # Used to debug scaling and position:
        # print(self._legend_items_group.get_world_bounding_box())
        # print(self._mesh.get_world_bounding_box())
        # print(self.world_object.get_world_bounding_box())
        # print(cam_w, cam_h)
        # print(scale_x, scale_y, scale)

        # # Update Position
        # wobj = self.world_object.world

        # pad2 = PADDING * 2
        # size = getattr(dock, "size", None)
        # if isinstance(size, (tuple, list)):
        #     dock_w, dock_h = size
        # elif size is None:
        #     dock_w = panel_w + pad2
        #     dock_h = panel_h + pad2
        # else:
        #     dock_w = dock_h = float(size)

        # dock_w = max(dock_w, panel_w + pad2)
        # dock_h = max(dock_h, panel_h + pad2)

        # wobj.x = max(PADDING, min(wobj.x, dock_w - panel_w - PADDING))
        # wobj.y = max(PADDING, min(wobj.y, dock_h - panel_h - PADDING))

    def remove_graphic(self, graphic: Graphic, *_, **__):
        """ Remove a graphic from the legend. """
        self._graphics.remove(graphic)
        legend_item = self._items.pop(graphic._fpl_address)
        self._legend_items_group.remove(legend_item.world_object)
        self._reset_item_positions()

    def _reset_item_positions(self):
        self._col_offsets = [0.0]
        col_spacing = self._col_spacing
        row_spacing = self._row_spacing

        for idx, legend_item in enumerate(self._items.values()):
            col_idx = idx // self._max_rows
            row_idx = idx % self._max_rows
            if col_idx >= len(self._col_offsets):
                prev_items = list(self._items.values())[col_idx * self._max_rows - self._max_rows : col_idx * self._max_rows]
                max_width = 0.0
                for item in prev_items:
                    bbox = item.world_object.get_world_bounding_box()
                    w, *_ = np.ptp(bbox, axis=0)
                    max_width = max(max_width, w)
                new_offset = self._col_offsets[-1] + max_width + col_spacing
                self._col_offsets.append(new_offset)
            x_pos = self._col_offsets[col_idx]
            y_pos = -row_idx * row_spacing
            legend_item.world_object.world.x = x_pos
            legend_item.world_object.world.y = y_pos

        if self._items:
            last_idx = len(self._items) - 1
            self._col_counter = last_idx // self._max_rows
            self._row_counter = (last_idx % self._max_rows) + 1
        else:
            self._col_counter = 0
            self._row_counter = 0

        # self._resize_dock_to_fit()
        self._reset_mesh_dims()

    # def _resize_dock_to_fit(self):
    #     if not self._items:
    #         return

    #     dock = self._plot_area
    #     if not hasattr(dock, "resize"):
    #         return

    #     bbox = self._legend_items_group.get_world_bounding_box()
    #     if bbox is None:
    #         return
    #     width, height, _ = np.ptp(bbox, axis=0)
    #     if width <= 0 or height <= 0:
    #         return

    #     pad2 = PADDING * 2.0
    #     target_w = width  + pad2
    #     target_h = height + pad2
    #     size = getattr(dock, "size", None)
    #     if isinstance(size, (tuple, list)):
    #         cur_w, cur_h = size
    #     else:
    #         cur_w = cur_h = float(size) if size is not None else target_w
    #     if (not isclose(target_w, cur_w, rel_tol=0.05) or
    #         not isclose(target_h, cur_h, rel_tol=0.05)):
    #         dock.resize((target_w, target_h))        

    def clear(self):
        """Clear all legend items."""
        for graphic in self.graphics:
            self.remove_graphic(graphic)
        self._col_counter = 0
        self._row_counter = 0
        self._col_offsets = [0.0]

    def reorder(self, labels: Iterable[str]):
        all_labels = [legend_item.label for legend_item in self._items.values()]

        if not set(labels) == set(all_labels):
            raise ValueError("Must pass all existing legend labels")

        new_items = OrderedDict()

        for label in labels:
            for graphic_loc, legend_item in self._items.items():
                if label == legend_item.label:
                    new_items[graphic_loc] = self._items.pop(graphic_loc)
                    break

        self._items = new_items
        self._reset_item_positions()

    def _pointer_down(self, ev):
        self._last_position = self._plot_area.map_screen_to_world(ev)
        self._initial_controller_state = self._plot_area.controller.enabled

    def _pointer_move(self, ev):
        if self._last_position is None:
            return

        self._plot_area.controller.enabled = False

        world_pos = self._plot_area.map_screen_to_world(ev)

        # outside viewport
        if world_pos is None:
            return

        delta = world_pos - self._last_position

        self.world_object.world.x = self.world_object.world.x + delta[0]
        self.world_object.world.y = self.world_object.world.y + delta[1]

        self._last_position = world_pos

        self._plot_area.controller.enabled = self._initial_controller_state

    def _pointer_up(self, ev):
        self._last_position = None
        if self._initial_controller_state is not None:
            self._plot_area.controller.enabled = self._initial_controller_state

    def __getitem__(self, graphic: Graphic) -> LegendItem:
        if not isinstance(graphic, Graphic):
            raise TypeError("Must index Legend with Graphics")

        if graphic._fpl_address not in self._items.keys():
            raise KeyError("Graphic not in legend")

        return self._items[graphic._fpl_address]

    def set_all_label_colors(self, color):
        """Set all legend item label colors."""
        col = pygfx.Color(color)
        for item in self._items.values():
            item.set_label_color(col)
        self.default_label_color = col

    def get_item(self, label: str) -> Optional[LegendItem]:
        """Return legend item by label (None if not found)."""
        for item in self._items.values():
            if item.label == label:
                return item
        return None

    def set_item_visible(self, label: str, visible: bool):
        """Show/hide a legend item (and its line/label)."""
        item = self.get_item(label)
        if not item:
            return
        item.world_object.visible = visible

    @property
    def graphics(self) -> tuple[Graphic, ...]:
        return tuple(self._graphics)

    @property
    def highlight_color(self):
        return self._highlight_color

    @highlight_color.setter
    def highlight_color(self, val):
        self._highlight_color = pygfx.Color(val)

    @property
    def background_color(self):
        return self._background_color

    @background_color.setter
    def background_color(self, val):
        self._background_color = pygfx.Color(val)
        mat = getattr(self._mesh, "material", None)
        if mat and hasattr(mat, "color"):
            mat.color = self._background_color

    @property
    def default_label_color(self):
        return self._default_label_color

    @default_label_color.setter
    def default_label_color(self, val):
        self._default_label_color = pygfx.Color(val)
        # Propagate to existing legend items
        for item in self._items.values():
            item.set_label_color(self._default_label_color)