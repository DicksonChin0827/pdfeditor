import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
from PIL import Image, ImageTk, ImageDraw
import fitz  # PyMuPDF
import io
import os
import json

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

HANDLE_SIZE  = 7
SEL_COLOR    = "#1f6aa5"
HANDLE_COLOR = "#ffffff"
SIGS_DIR     = os.path.join(os.path.dirname(__file__), "signatures")
SIGS_META    = os.path.join(SIGS_DIR, "signatures.json")

FONT_FAMILIES = ["Arial", "Times New Roman", "Courier New",
                 "Georgia", "Verdana", "Helvetica", "Calibri"]

PDF_FONTS = {           # PyMuPDF built-in font names
    "Arial":           "helv",
    "Times New Roman": "tiro",
    "Courier New":     "cour",
    "Georgia":         "tiro",
    "Verdana":         "helv",
    "Helvetica":       "helv",
    "Calibri":         "helv",
}

def ensure_sigs_dir():
    os.makedirs(SIGS_DIR, exist_ok=True)
    if not os.path.exists(SIGS_META):
        with open(SIGS_META, "w") as f: json.dump([], f)

def load_sigs_meta():
    ensure_sigs_dir()
    with open(SIGS_META) as f: return json.load(f)

def save_sigs_meta(data):
    with open(SIGS_META, "w") as f: json.dump(data, f, indent=2)

def hex_to_rgb01(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16)/255 for i in (0, 2, 4))


# ─────────────────────────────────────────────────────────────────────────────
# Signature Draw & Save Dialog
# ─────────────────────────────────────────────────────────────────────────────
class SignatureDrawDialog(ctk.CTkToplevel):
    def __init__(self, master, on_save):
        super().__init__(master)
        self.title("Draw & Save Signature")
        self.geometry("540x420")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.on_save = on_save

        ctk.CTkLabel(self, text="Signature Name:").pack(pady=(14, 0))
        self.name_entry = ctk.CTkEntry(self, width=300,
                                       placeholder_text="e.g. My Signature")
        self.name_entry.pack(pady=6)

        ctk.CTkLabel(self, text="Draw below:").pack()
        self.canvas = tk.Canvas(self, bg="white", width=500, height=200,
                                cursor="pencil", bd=2, relief="solid")
        self.canvas.pack(pady=6)

        self.pil_img  = Image.new("RGBA", (500, 200), (255, 255, 255, 0))
        self.pil_draw = ImageDraw.Draw(self.pil_img)
        self.lx = self.ly = None

        self.canvas.bind("<Button-1>",        lambda e: self._s(e))
        self.canvas.bind("<B1-Motion>",       lambda e: self._d(e))
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, 'lx', None))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=10)
        ctk.CTkButton(bf, text="Clear",  width=90,  command=self._clear).pack(side="left", padx=8)
        ctk.CTkButton(bf, text="Save Signature", width=160,
                      fg_color="#28a745", hover_color="#218838",
                      command=self._save).pack(side="left", padx=8)

    def _s(self, e): self.lx, self.ly = e.x, e.y
    def _d(self, e):
        if self.lx is not None:
            self.canvas.create_line(self.lx, self.ly, e.x, e.y,
                                    fill="black", width=3, capstyle=tk.ROUND, smooth=True)
            self.pil_draw.line([self.lx, self.ly, e.x, e.y],
                               fill="black", width=3, joint="curve")
        self.lx, self.ly = e.x, e.y

    def _clear(self):
        self.canvas.delete("all")
        self.pil_img  = Image.new("RGBA", (500, 200), (255, 255, 255, 0))
        self.pil_draw = ImageDraw.Draw(self.pil_img)

    def _save(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please enter a name."); return
        bbox    = self.pil_img.getbbox()
        cropped = self.pil_img.crop(bbox) if bbox else self.pil_img
        safe    = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        path    = os.path.join(SIGS_DIR, f"{safe}.png")
        cropped.save(path, "PNG")
        metas = [m for m in load_sigs_meta() if m["name"] != name]
        metas.append({"name": name, "path": path})
        save_sigs_meta(metas)
        self.on_save(name, path)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Signature Manager
# ─────────────────────────────────────────────────────────────────────────────
class SignatureManagerDialog(ctk.CTkToplevel):
    def __init__(self, master, on_insert):
        super().__init__(master)
        self.title("Signature Manager")
        self.geometry("560x460")
        self.attributes("-topmost", True)
        self.on_insert  = on_insert
        self.thumb_refs = []

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 4))
        ctk.CTkLabel(top, text="My Signatures",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="+ New Signature", width=140,
                      command=self._new).pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, width=520, height=340)
        self.scroll.pack(padx=14, pady=8, fill="both", expand=True)
        ctk.CTkLabel(self, text="Click 'Insert' to place a signature on the PDF.",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0,8))
        self._refresh()

    def _refresh(self):
        for w in self.scroll.winfo_children(): w.destroy()
        self.thumb_refs = []
        metas = load_sigs_meta()
        if not metas:
            ctk.CTkLabel(self.scroll,
                         text="No saved signatures.\nClick '+ New Signature'.",
                         text_color="gray").pack(pady=40)
            return
        cols = 3
        for idx, meta in enumerate(metas):
            r, c = divmod(idx, cols)
            cell = ctk.CTkFrame(self.scroll, corner_radius=8,
                                fg_color=("gray85","gray20"))
            cell.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
            try:
                img = Image.open(meta["path"]).convert("RGBA")
                img.thumbnail((140, 70))
                bg  = Image.new("RGBA", img.size, (255,255,255,255))
                bg.paste(img, mask=img)
                tk_img = ImageTk.PhotoImage(bg)
                self.thumb_refs.append(tk_img)
                lbl = tk.Label(cell, image=tk_img, bg="#2b2b2b", cursor="hand2")
                lbl.pack(pady=(8,2))
                lbl.bind("<Button-1>", lambda e, m=meta: self._insert(m))
            except: ctk.CTkLabel(cell, text="[error]").pack()
            ctk.CTkLabel(cell, text=meta["name"],
                         font=ctk.CTkFont(size=11)).pack()
            br = ctk.CTkFrame(cell, fg_color="transparent")
            br.pack(pady=(2,8))
            ctk.CTkButton(br, text="Insert", width=60,
                          command=lambda m=meta: self._insert(m)).pack(side="left", padx=2)
            ctk.CTkButton(br, text="Delete", width=60,
                          fg_color="#dc3545", hover_color="#c82333",
                          command=lambda m=meta: self._delete(m)).pack(side="left", padx=2)

    def _new(self): SignatureDrawDialog(self, lambda n, p: self._refresh())
    def _insert(self, meta): self.on_insert(meta["path"]); self.destroy()
    def _delete(self, meta):
        if messagebox.askyesno("Delete", f"Delete '{meta['name']}'?"):
            try: os.remove(meta["path"])
            except: pass
            metas = [m for m in load_sigs_meta() if m["name"] != meta["name"]]
            save_sigs_meta(metas)
            self._refresh()


# ─────────────────────────────────────────────────────────────────────────────
# Page Manager
# ─────────────────────────────────────────────────────────────────────────────
class PageManagerDialog(ctk.CTkToplevel):
    def __init__(self, master, num_pages, current_page, callback):
        super().__init__(master)
        self.title("Reorder Pages")
        self.geometry("340x210")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.callback  = callback
        self.num_pages = num_pages
        ctk.CTkLabel(self, text=f"Total pages: {num_pages}", font=("Arial",13)).pack(pady=(16,4))
        ctk.CTkLabel(self, text=f"Current page: {current_page+1}", font=("Arial",13)).pack(pady=4)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=10)
        ctk.CTkLabel(row, text="Move to position:").pack(side="left", padx=6)
        self.entry = ctk.CTkEntry(row, width=70, placeholder_text="1…")
        self.entry.pack(side="left")
        ctk.CTkButton(self, text="Apply", fg_color="#28a745", hover_color="#218838",
                      command=self.apply).pack(pady=8)

    def apply(self):
        try:
            pos = int(self.entry.get()) - 1
            if not (0 <= pos < self.num_pages): raise ValueError
            self.callback(pos); self.destroy()
        except ValueError:
            messagebox.showerror("Invalid", f"Enter 1–{self.num_pages}.")


# ─────────────────────────────────────────────────────────────────────────────
# Text Formatting Bar  (appears at top of canvas area when text is active)
# ─────────────────────────────────────────────────────────────────────────────
class TextFormatBar(ctk.CTkFrame):
    def __init__(self, master, on_change):
        super().__init__(master, corner_radius=0, height=44,
                         fg_color=("gray90","gray18"))
        self.on_change = on_change

        # Font family
        self.family_var = ctk.StringVar(value="Arial")
        self.family_menu = ctk.CTkOptionMenu(
            self, values=FONT_FAMILIES, variable=self.family_var,
            width=150, command=lambda _: self._changed())
        self.family_menu.pack(side="left", padx=(10,4), pady=6)

        # Font size
        ctk.CTkLabel(self, text="Size:").pack(side="left")
        self.size_var = tk.IntVar(value=12)
        self.size_spin = ctk.CTkEntry(self, width=46,
                                      textvariable=self.size_var)
        self.size_spin.pack(side="left", padx=4)
        self.size_spin.bind("<Return>", lambda e: self._changed())
        self.size_spin.bind("<FocusOut>", lambda e: self._changed())

        ctk.CTkButton(self, text="–", width=28,
                      command=lambda: self._step_size(-1)).pack(side="left", padx=1)
        ctk.CTkButton(self, text="+", width=28,
                      command=lambda: self._step_size(1)).pack(side="left", padx=1)

        # Bold / Italic toggles
        self.bold_var   = tk.BooleanVar(value=False)
        self.italic_var = tk.BooleanVar(value=False)

        self.bold_btn = ctk.CTkButton(
            self, text="B", width=36,
            font=ctk.CTkFont(weight="bold"),
            command=self._toggle_bold)
        self.bold_btn.pack(side="left", padx=(10,2))

        self.italic_btn = ctk.CTkButton(
            self, text="I", width=36,
            font=ctk.CTkFont(slant="italic"),
            command=self._toggle_italic)
        self.italic_btn.pack(side="left", padx=2)

        # Alignment
        self.align_var = ctk.StringVar(value="Left")
        self.align_seg = ctk.CTkSegmentedButton(
            self, values=["Left", "Center", "Right"],
            variable=self.align_var,
            command=lambda _: self._changed())
        self.align_seg.pack(side="left", padx=(10,4))

        # Color swatch
        self.color_hex = "#000000"
        self.color_btn = tk.Button(
            self, bg=self.color_hex, width=3, cursor="hand2",
            relief="flat", bd=2,
            command=self._pick_color)
        self.color_btn.pack(side="left", padx=(10,4))
        ctk.CTkLabel(self, text="Color").pack(side="left")

        # Quick colors
        for c in ["#000000","#c0392b","#2980b9","#27ae60","#8e44ad","#e67e22"]:
            b = tk.Button(self, bg=c, width=2, cursor="hand2",
                          relief="flat", bd=1,
                          command=lambda col=c: self._set_color(col))
            b.pack(side="left", padx=1)

    # ── internal ──────────────────────────────────────────────────────────────
    def _changed(self, *_):
        self.on_change(self.get_fmt())

    def _step_size(self, delta):
        try:
            v = max(4, int(self.size_var.get()) + delta)
            self.size_var.set(v)
        except: self.size_var.set(12)
        self._changed()

    def _toggle_bold(self):
        self.bold_var.set(not self.bold_var.get())
        self._update_toggle_btns()
        self._changed()

    def _toggle_italic(self):
        self.italic_var.set(not self.italic_var.get())
        self._update_toggle_btns()
        self._changed()

    def _update_toggle_btns(self):
        self.bold_btn.configure(
            fg_color="#1f6aa5" if self.bold_var.get() else ("gray75","gray25"))
        self.italic_btn.configure(
            fg_color="#1f6aa5" if self.italic_var.get() else ("gray75","gray25"))

    def _pick_color(self):
        result = colorchooser.askcolor(color=self.color_hex, title="Pick text color")
        if result and result[1]:
            self._set_color(result[1])

    def _set_color(self, hex_col):
        self.color_hex = hex_col
        self.color_btn.configure(bg=hex_col)
        self._changed()

    # ── public ────────────────────────────────────────────────────────────────
    def get_fmt(self):
        try:    size = max(4, int(self.size_var.get()))
        except: size = 12
        return {
            "family":  self.family_var.get(),
            "size":    size,
            "bold":    self.bold_var.get(),
            "italic":  self.italic_var.get(),
            "color":   self.color_hex,
            "align":   self.align_var.get(),
        }

    def set_fmt(self, fmt):
        self.family_var.set(fmt.get("family", "Arial"))
        self.size_var.set(fmt.get("size", 12))
        self.bold_var.set(fmt.get("bold", False))
        self.italic_var.set(fmt.get("italic", False))
        self.align_var.set(fmt.get("align", "Left"))
        self._set_color(fmt.get("color", "#000000"))
        self._update_toggle_btns()

    def show(self): self.grid(row=0, column=0, sticky="ew")
    def hide(self): self.grid_forget()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def tk_font_tuple(fmt, zoom=1.0):
    family = fmt.get("family", "Arial")
    size   = max(6, int(fmt.get("size", 12) * zoom))
    weight = "bold"   if fmt.get("bold")   else "normal"
    slant  = "italic" if fmt.get("italic") else "roman"
    return (family, size, weight, slant)

def default_fmt():
    return {"family":"Arial","size":12,"bold":False,"italic":False,"color":"#000000","align":"Left"}


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────
class PDFEditor(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Advanced PDF Editor Pro")
        self.geometry("1300x880")
        ensure_sigs_dir()

        self.doc              = None
        self.current_page_idx = 0
        self.zoom             = 1.5

        self.history     = []
        self.history_idx = -1

        self.floating_items  = []
        self.selected_item   = None
        self.drag_mode       = None
        self.drag_start_x    = self.drag_start_y = 0
        self.drag_item_x     = self.drag_item_y  = 0
        self.drag_item_w     = self.drag_item_h  = 0

        self.redact_start_x  = self.redact_start_y = 0
        self.redact_rect_id  = None

        self.current_mode    = None

        self._inline_widget  = None   # (frame, text_widget, win_id, cx, cy, fmt)
        self._inline_is_edit = False
        self._edit_block     = None

        self.setup_ui()

    # ── UI Setup ──────────────────────────────────────────────────────────────
    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Sidebar
        sb = ctk.CTkFrame(self, width=215, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_rowconfigure(14, weight=1)
        self.sidebar = sb

        ctk.CTkLabel(sb, text="PDF Editor Pro",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(22,4))
        self.lbl_mode = ctk.CTkLabel(sb, text="Mode: View",
                                     font=ctk.CTkFont(size=11),
                                     text_color="#1f6aa5")
        self.lbl_mode.grid(row=1, column=0, padx=20, pady=(0,12))

        ctk.CTkLabel(sb, text="File",
                     font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, padx=20, pady=(4,2))
        ctk.CTkButton(sb, text="Open PDF", command=self.open_pdf).grid(
            row=3, column=0, padx=20, pady=4)
        ctk.CTkButton(sb, text="Save PDF", fg_color="#28a745",
                      hover_color="#218838", command=self.save_pdf).grid(
            row=4, column=0, padx=20, pady=4)

        ctk.CTkLabel(sb, text="Tools",
                     font=ctk.CTkFont(weight="bold")).grid(row=5, column=0, padx=20, pady=(14,2))
        self._tool_btns = {}
        for label, mode, r in [
            ("Add Text",        'text',      6),
            ("Edit Existing",   'edit_text', 7),
            ("Insert Image",    'image',     8),
            ("Remove / Redact", 'redact',    9),
        ]:
            kw = dict(fg_color="#dc3545", hover_color="#c82333") if mode == 'redact' else {}
            btn = ctk.CTkButton(sb, text=label,
                                command=lambda m=mode: self.set_mode(m), **kw)
            btn.grid(row=r, column=0, padx=20, pady=4)
            self._tool_btns[mode] = btn

        ctk.CTkLabel(sb, text="Signatures",
                     font=ctk.CTkFont(weight="bold")).grid(row=10, column=0, padx=20, pady=(14,2))
        ctk.CTkButton(sb, text="Signature Manager",
                      command=self.open_sig_manager).grid(row=11, column=0, padx=20, pady=4)

        ctk.CTkLabel(sb, text="Pages",
                     font=ctk.CTkFont(weight="bold")).grid(row=12, column=0, padx=20, pady=(14,2))
        ctk.CTkButton(sb, text="Reorder Pages",
                      command=self.open_page_manager).grid(row=13, column=0, padx=20, pady=4)

        # Commit Objects button removed for auto-commit workflow
        uf = ctk.CTkFrame(sb, fg_color="transparent")
        uf.grid(row=16, column=0, padx=20, pady=4)
        self.btn_undo = ctk.CTkButton(uf, text="Undo", width=60,
                                      state="disabled", command=self.undo)
        self.btn_undo.pack(side="left", padx=2)
        self.btn_redo = ctk.CTkButton(uf, text="Redo", width=60,
                                      state="disabled", command=self.redo)
        self.btn_redo.pack(side="left", padx=2)
        ctk.CTkLabel(sb,
                     text="Drag corners to resize\nDrag center to move\nEsc = deselect",
                     font=ctk.CTkFont(size=10), text_color="gray").grid(
            row=17, column=0, pady=(10,16))

        # Main area
        mf = ctk.CTkFrame(self, corner_radius=0)
        mf.grid(row=0, column=1, sticky="nsew")
        mf.grid_columnconfigure(0, weight=1)
        mf.grid_rowconfigure(1, weight=1)   # canvas row gets weight
        self.main_frame = mf

        # ── Text format bar (row 0) ───────────────────────────────────────────
        self.fmt_bar = TextFormatBar(mf, self._on_fmt_change)
        # not gridded yet; shown/hidden by show/hide

        # ── Nav bar (row 2) ───────────────────────────────────────────────────
        nav = ctk.CTkFrame(mf, height=44, corner_radius=0)
        nav.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(nav, text="< Prev", width=80,
                      command=self.prev_page).pack(side="left", padx=20, pady=8)
        self.lbl_page = ctk.CTkLabel(nav, text="Page 0 / 0",
                                     font=ctk.CTkFont(weight="bold"))
        self.lbl_page.pack(side="left", expand=True)
        ctk.CTkButton(nav, text="Next >", width=80,
                      command=self.next_page).pack(side="right", padx=20, pady=8)

        # ── Canvas (row 1) ────────────────────────────────────────────────────
        self.canvas = tk.Canvas(mf, bg="#1e1e1e", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")

        sy = ctk.CTkScrollbar(mf, orientation="vertical",
                               command=self.canvas.yview)
        sy.grid(row=1, column=1, sticky="ns")
        sx = ctk.CTkScrollbar(mf, orientation="horizontal",
                               command=self.canvas.xview)
        sx.grid(row=3, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)

        self.canvas.bind("<Button-1>",        self.on_click)
        self.canvas.bind("<B1-Motion>",       self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.deselect())

    # ── Format bar logic ──────────────────────────────────────────────────────

    def _show_fmt_bar(self, fmt=None):
        if fmt: self.fmt_bar.set_fmt(fmt)
        self.fmt_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.main_frame.grid_rowconfigure(0, minsize=44)

    def _hide_fmt_bar(self):
        self.fmt_bar.grid_forget()
        self.main_frame.grid_rowconfigure(0, minsize=0)

    def _on_fmt_change(self, fmt):
        """Called when user changes formatting in the bar."""
        # Update inline editor if open
        if self._inline_widget:
            _, txt_widget, _, _, _, _ = self._inline_widget
            new_font = tk_font_tuple(fmt, self.zoom)
            txt_widget.configure(font=new_font,
                                 fg=fmt.get("color","#000000"))
            # update stored fmt in tuple
            frame, tw, wid, cx, cy, _ = self._inline_widget
            self._inline_widget = (frame, tw, wid, cx, cy, fmt)
        # Update selected text item live
        if self.selected_item and self.selected_item['type'] == 'text':
            self.selected_item['fmt'] = fmt
            self._refresh_text(self.selected_item)
            self._draw_selection(self.selected_item)

    # ── Mode ──────────────────────────────────────────────────────────────────
    def set_mode(self, mode):
        self._commit_inline()
        self.current_mode = mode
        labels = {
            'text':      "Mode: Click to Add Text",
            'edit_text': "Mode: Click Text to Edit",
            'image':     "Mode: Click to Insert Image",
            'redact':    "Mode: Drag to Redact",
        }
        self.lbl_mode.configure(text=labels.get(mode, "Mode: View / Select"))
        for m, btn in self._tool_btns.items():
            btn.configure(border_width=2 if m == mode else 0,
                          border_color="#ffffff")

        if mode in ('text', 'edit_text'):
            self._show_fmt_bar()
        else:
            if self.selected_item is None or \
               self.selected_item['type'] != 'text':
                self._hide_fmt_bar()

    # ── File ──────────────────────────────────────────────────────────────────
    def open_pdf(self):
        fp = filedialog.askopenfilename(filetypes=[("PDF files","*.pdf")])
        if fp:
            self._commit_inline()
            self.doc = fitz.open(fp)
            self.current_page_idx = 0
            self.history = []; self.history_idx = -1
            self.save_state(); self.render_page()

    def save_pdf(self):
        if not self.doc: return
        self._commit_inline(); self.commit_floating_items()
        fp = filedialog.asksaveasfilename(defaultextension=".pdf",
                                          filetypes=[("PDF files","*.pdf")])
        if fp:
            self.doc.save(fp)
            messagebox.showinfo("Saved", "PDF saved!")

    # ── History ───────────────────────────────────────────────────────────────
    def save_state(self):
        if not self.doc: return
        if self.history_idx < len(self.history)-1:
            self.history = self.history[:self.history_idx+1]
        self.history.append(self.doc.write())
        self.history_idx += 1
        self._upd_hist()

    def load_state(self, idx):
        if 0 <= idx < len(self.history):
            self.history_idx = idx
            self.doc = fitz.open("pdf", self.history[idx])
            self._upd_hist(); self.render_page()

    def undo(self):
        self._commit_inline(); self.commit_floating_items()
        if self.history_idx > 0: self.load_state(self.history_idx-1)

    def redo(self):
        self._commit_inline(); self.commit_floating_items()
        if self.history_idx < len(self.history)-1:
            self.load_state(self.history_idx+1)

    def _upd_hist(self):
        self.btn_undo.configure(state="normal" if self.history_idx > 0 else "disabled")
        self.btn_redo.configure(state="normal" if self.history_idx < len(self.history)-1 else "disabled")

    # ── Navigation ────────────────────────────────────────────────────────────
    def prev_page(self):
        self._commit_inline(); self.commit_floating_items()
        if self.doc and self.current_page_idx > 0:
            self.current_page_idx -= 1; self.render_page()

    def next_page(self):
        self._commit_inline(); self.commit_floating_items()
        if self.doc and self.current_page_idx < len(self.doc)-1:
            self.current_page_idx += 1; self.render_page()

    # ── Page manager ──────────────────────────────────────────────────────────
    def open_page_manager(self):
        if not self.doc:
            messagebox.showinfo("No PDF","Open a PDF first."); return
        self._commit_inline(); self.commit_floating_items()
        PageManagerDialog(self, len(self.doc),
                          self.current_page_idx, self._do_move_page)

    def _do_move_page(self, target_pos):
        self.doc.move_page(self.current_page_idx, target_pos)
        self.current_page_idx = target_pos
        self.save_state(); self.render_page()
        messagebox.showinfo("Done", f"Page moved to position {target_pos+1}.")

    # ── Signature manager ─────────────────────────────────────────────────────
    def open_sig_manager(self):
        SignatureManagerDialog(self, self._insert_sig_from_path)

    def _insert_sig_from_path(self, filepath):
        if not self.doc:
            messagebox.showinfo("No PDF","Open a PDF first."); return
        try:
            pil = Image.open(filepath)
            c_x = self.canvas.canvasx(220)
            c_y = self.canvas.canvasy(220)
            item = self._make_image_item(c_x, c_y, filepath, pil)
            self.deselect()
            self.selected_item = item
            self._draw_selection(item)
            self.set_mode(None)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Render ────────────────────────────────────────────────────────────────
    def render_page(self):
        if not self.doc: return
        self._commit_inline(); self._clear_floating()
        page = self.doc[self.current_page_idx]
        pix  = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        img  = Image.open(io.BytesIO(pix.tobytes("ppm")))
        self.tk_image = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW,
                                 image=self.tk_image, tags="bg")
        self.canvas.config(scrollregion=self.canvas.bbox(tk.ALL))
        self.lbl_page.configure(
            text=f"Page {self.current_page_idx+1} / {len(self.doc)}")
        self.selected_item = None; self.drag_mode = None

    def _clear_floating(self):
        for it in self.floating_items:
            self.canvas.delete(it['id'])
            if it.get('box_id'): self.canvas.delete(it['box_id'])
            for h in it.get('handles',[]): self.canvas.delete(h)
        self.floating_items = []; self.selected_item = None

    def _c2p(self, x, y): return x/self.zoom, y/self.zoom

    # ── Selection handles ─────────────────────────────────────────────────────
    def _draw_selection(self, item):
        x,y,w,h = item['x'],item['y'],item['w'],item['h']
        hs = HANDLE_SIZE
        if item.get('box_id'): self.canvas.delete(item['box_id'])
        for hid in item.get('handles',[]): self.canvas.delete(hid)
        box = self.canvas.create_rectangle(x,y,x+w,y+h,
                                           outline=SEL_COLOR, width=2,
                                           dash=(4,3), tags="selection")
        item['box_id'] = box
        corners = [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]
        handles = []
        for (cx,cy) in corners:
            hid = self.canvas.create_rectangle(
                cx-hs,cy-hs,cx+hs,cy+hs,
                fill=HANDLE_COLOR, outline=SEL_COLOR, width=2,
                tags="selection")
            handles.append(hid)
        item['handles'] = handles

    def _remove_selection(self, item):
        if item.get('box_id'):
            self.canvas.delete(item['box_id']); item['box_id']=None
        for hid in item.get('handles',[]): self.canvas.delete(hid)
        item['handles'] = []

    def _hit_handle(self, cx, cy, item):
        hs = HANDLE_SIZE+6
        x,y,w,h = item['x'],item['y'],item['w'],item['h']
        for mode,(px,py) in {'resize_NW':(x,y),'resize_NE':(x+w,y),
                              'resize_SE':(x+w,y+h),'resize_SW':(x,y+h)}.items():
            if abs(cx-px)<=hs and abs(cy-py)<=hs: return mode
        return None

    def deselect(self):
        just_closed_editor = self._commit_inline()
        if self.selected_item:
            self._remove_selection(self.selected_item)
        self.selected_item = None
        self.drag_mode = None
        if self.current_mode not in ('text','edit_text'):
            self._hide_fmt_bar()
        if self.floating_items and not just_closed_editor:
            self.commit_floating_items()

    # ── Inline editor ─────────────────────────────────────────────────────────
    def _open_inline_editor(self, c_x, c_y,
                             initial_text="",
                             is_edit=False,
                             edit_block=None,
                             fmt=None):
        self._commit_inline()
        if fmt is None: fmt = self.fmt_bar.get_fmt()

        tk_font = tk_font_tuple(fmt, self.zoom)
        color   = fmt.get("color","#000000")

        frame = tk.Frame(self.canvas, bg="white", bd=0,
                         relief="flat", cursor="xterm")
        txt = tk.Text(frame, wrap="word", bd=0,
                      bg="white", fg=color,
                      font=tk_font,
                      width=22, height=3,
                      insertbackground=color)
        txt.pack(fill="both", expand=True)
        if initial_text:
            txt.insert("1.0", initial_text)
            txt.tag_add("sel","1.0","end")

        win_id = self.canvas.create_window(c_x, c_y, anchor=tk.NW,
                                           window=frame,
                                           tags="inline_editor")
        self._inline_widget  = (frame, txt, win_id, c_x, c_y, fmt)
        self._inline_is_edit = is_edit
        self._edit_block     = edit_block
        txt.focus_set()

        txt.bind("<FocusOut>",     lambda e: self._commit_inline())
        txt.bind("<Control-Return>", lambda e: self._commit_inline())

    def _commit_inline(self):
        if self._inline_widget is None: return False
        frame, txt, win_id, c_x, c_y, fmt = self._inline_widget
        text = txt.get("1.0","end-1c").strip()
        self._inline_widget = None   # clear first

        self.canvas.delete(win_id)
        try: frame.destroy()
        except: pass

        if not text:
            self._inline_is_edit = False; self._edit_block = None
            return

        if self._inline_is_edit and self._edit_block:
            # Commit any existing items before rendering page to prevent them from being wiped out
            if self.floating_items:
                self.commit_floating_items()

            b_rect = fitz.Rect(self._edit_block[:4])
            page   = self.doc[self.current_page_idx]
            page.add_redact_annot(b_rect, fill=(1,1,1))
            page.apply_redactions()
            self.save_state(); self.render_page()
            # Position the floating item at exact block top-left on canvas
            c_x2 = self._edit_block[0] * self.zoom
            c_y2 = self._edit_block[1] * self.zoom
            item = self._make_text_item(c_x2, c_y2, text, fmt)
            # Store the original PDF rect so commit_floating_items can use
            # insert_textbox for pixel-perfect re-placement
            item['pdf_rect'] = b_rect
            self._inline_is_edit = False; self._edit_block = None
        else:
            item = self._make_text_item(c_x, c_y, text, fmt)

        if self.selected_item:
            self._remove_selection(self.selected_item)
        self.selected_item = item
        self._draw_selection(item)

        # Automatically exit "Add Text" mode after adding one
        if self.current_mode == 'text':
            self.current_mode = None
            self.lbl_mode.configure(text="Mode: View / Select")
            for m, btn in self._tool_btns.items():
                btn.configure(border_width=0)
                
        return True

    # ── Floating items ────────────────────────────────────────────────────────
    def _make_text_item(self, c_x, c_y, text, fmt=None):
        if fmt is None: fmt = self.fmt_bar.get_fmt()
        tk_font = tk_font_tuple(fmt, self.zoom)
        color   = fmt.get("color","#000000")
        tid = self.canvas.create_text(c_x, c_y, text=text,
                                      fill=color, font=tk_font,
                                      anchor=tk.NW, tags="floating")
        bbox = self.canvas.bbox(tid) or (c_x, c_y, c_x+80, c_y+fmt['size']+4)
        item = dict(type='text', id=tid, box_id=None, handles=[],
                    val=text, fmt=fmt,
                    x=c_x, y=c_y,
                    w=bbox[2]-bbox[0], h=bbox[3]-bbox[1],
                    orig_img=None, img_ref=None)
        self.floating_items.append(item)
        return item

    def _make_image_item(self, c_x, c_y, filepath, pil_img=None):
        if pil_img is None: pil_img = Image.open(filepath)
        ow,oh   = pil_img.size
        ratio   = min(180/max(ow,1), 180/max(oh,1), 1.0)
        dw = max(10, int(ow*ratio*self.zoom))
        dh = max(10, int(oh*ratio*self.zoom))
        resized = pil_img.resize((dw,dh), Image.Resampling.LANCZOS)
        tk_img  = ImageTk.PhotoImage(resized)
        iid = self.canvas.create_image(c_x,c_y, anchor=tk.NW,
                                       image=tk_img, tags="floating")
        item = dict(type='image', id=iid, box_id=None, handles=[],
                    val=filepath, fmt=default_fmt(),
                    x=c_x, y=c_y, w=dw, h=dh,
                    orig_img=pil_img, img_ref=tk_img)
        self.floating_items.append(item)
        return item

    def _refresh_text(self, item):
        fmt     = item['fmt']
        tk_font = tk_font_tuple(fmt, self.zoom)
        align   = fmt.get("align", "Left").lower()
        if align not in ("left", "center", "right"): align = "left"
        self.canvas.itemconfig(item['id'],
                               font=tk_font,
                               fill=fmt.get("color","#000000"),
                               width=item['w'],
                               justify=align)
        self.canvas.coords(item['id'], item['x'], item['y'])
        bbox = self.canvas.bbox(item['id'])
        if bbox:
            # Only update height based on new wrap; keep the user-defined width
            item['h'] = bbox[3]-bbox[1]

    def _refresh_image(self, item):
        dw = max(4, int(item['w']))
        dh = max(4, int(item['h']))
        resized = item['orig_img'].resize((dw,dh), Image.Resampling.LANCZOS)
        tk_img  = ImageTk.PhotoImage(resized)
        item['img_ref'] = tk_img
        self.canvas.itemconfig(item['id'], image=tk_img)
        self.canvas.coords(item['id'], item['x'], item['y'])

    # ── Commit to PDF ──────────────────────────────────────────────────────────
    def commit_floating_items(self):
        if not self.doc or not self.floating_items: return
        
        if self.selected_item:
            self._remove_selection(self.selected_item)
            self.selected_item = None
            self.drag_mode = None
            
        page = self.doc[self.current_page_idx]
        for it in self.floating_items:
            px, py = self._c2p(it['x'], it['y'])
            if it['type'] == 'text':
                fmt    = it['fmt']
                fs     = fmt.get('size', 12)
                color  = hex_to_rgb01(fmt.get('color', '#000000'))
                
                # Calculate the exact rect based on the current width/height
                pw = it['w'] / self.zoom
                ph = it['h'] / self.zoom
                
                # Provide massive vertical space to guarantee PyMuPDF never truncates/hides the text
                r = fitz.Rect(px, py, px + pw, py + 1000)
                
                if it.get('pdf_rect'):
                    # If this was an edit, we redact the old area again just in case
                    # (Though it was already redacted when inline editor opened)
                    pass

                # Map string alignment to PyMuPDF alignment int
                align_str = fmt.get("align", "Left").lower()
                align_int = 1 if align_str == "center" else 2 if align_str == "right" else 0

                page.insert_textbox(
                    r, it['val'],
                    fontsize=fs,
                    color=color,
                    align=align_int)

            elif it['type'] == 'image':
                pw = it['w'] / self.zoom
                ph = it['h'] / self.zoom
                page.insert_image(
                    fitz.Rect(px, py, px + pw, py + ph),
                    filename=it['val'])
        self.save_state(); self.render_page()

    # ── Canvas events ─────────────────────────────────────────────────────────
    def _find_fl(self, cid):
        for it in self.floating_items:
            if it['id'] == cid: return it
        return None

    def on_click(self, event):
        if not self.doc: return
        c_x = self.canvas.canvasx(event.x)
        c_y = self.canvas.canvasy(event.y)

        if self.current_mode == 'redact':
            self._commit_inline(); self.deselect()
            self.redact_start_x = c_x; self.redact_start_y = c_y
            self.redact_rect_id = self.canvas.create_rectangle(
                c_x,c_y,c_x,c_y,
                outline='#dc3545', fill='#dc3545', stipple='gray50')
            return

        if self.selected_item:
            hm = self._hit_handle(c_x, c_y, self.selected_item)
            if hm:
                self._commit_inline()
                self.drag_mode    = hm
                self.drag_start_x = c_x; self.drag_start_y = c_y
                self.drag_item_x  = self.selected_item['x']
                self.drag_item_y  = self.selected_item['y']
                self.drag_item_w  = self.selected_item['w']
                self.drag_item_h  = self.selected_item['h']
                return

        # New reliable bounding box hit detection for floating items
        clicked_fl = None
        for it in reversed(self.floating_items):
            x, y, w, h = it['x'], it['y'], it['w'], it['h']
            # allow a generous 4-pixel margin for easy clicking
            if x - 4 <= c_x <= x + w + 4 and y - 4 <= c_y <= y + h + 4:
                clicked_fl = it
                break

        if clicked_fl:
            self._commit_inline()
            if self.selected_item and self.selected_item is not clicked_fl:
                self._remove_selection(self.selected_item)
            self.selected_item = clicked_fl
            self._draw_selection(clicked_fl)
            if clicked_fl['type'] == 'text':
                self._show_fmt_bar(clicked_fl['fmt'])
            else:
                self._hide_fmt_bar()
            self.drag_mode = 'move'
            self.drag_start_x = c_x; self.drag_start_y = c_y
            self.drag_item_x = clicked_fl['x']; self.drag_item_y = clicked_fl['y']
            return

        # background click
        self.deselect()
        pdf_x, pdf_y = self._c2p(c_x, c_y)

        if self.current_mode == 'text':
            self._show_fmt_bar()
            self._open_inline_editor(c_x, c_y)

        elif self.current_mode == 'edit_text':
            page = self.doc[self.current_page_idx]
            text_dict = page.get_text("dict")
            
            clicked_line = None
            for block in text_dict.get("blocks", []):
                if block.get("type", 1) != 0: continue
                b_rect = fitz.Rect(block.get("bbox", [0,0,0,0]))
                if b_rect.contains(fitz.Point(pdf_x, pdf_y)):
                    best_line = None
                    best_dist = float('inf')
                    for line in block.get("lines", []):
                        l_rect = fitz.Rect(line.get("bbox", [0,0,0,0]))
                        # expand slightly for easier clicking
                        expanded = l_rect + (-2, -4, 2, 4)
                        if expanded.contains(fitz.Point(pdf_x, pdf_y)):
                            clicked_line = line
                            break
                        # fallback: find closest line vertically
                        cy = (l_rect.y0 + l_rect.y1) / 2
                        dist = abs(cy - pdf_y)
                        if dist < best_dist:
                            best_dist = dist
                            best_line = line
                    if not clicked_line:
                        clicked_line = best_line
                    break

            if clicked_line:
                old_text = "".join(span.get("text", "") for span in clicked_line.get("spans", []))
                bbox = clicked_line["bbox"]
                self._show_fmt_bar()
                edit_tuple = (bbox[0], bbox[1], bbox[2], bbox[3], old_text)
                self._open_inline_editor(
                    bbox[0]*self.zoom, bbox[1]*self.zoom,
                    initial_text=old_text.strip(), is_edit=True, edit_block=edit_tuple)
                # The editor's FocusOut / Ctrl+Enter will handle commit automatically.

        elif self.current_mode == 'image':
            fp = filedialog.askopenfilename(
                filetypes=[("Images","*.png;*.jpg;*.jpeg")])
            if fp:
                try:
                    item = self._make_image_item(c_x, c_y, fp)
                    self.selected_item = item
                    self._draw_selection(item)
                except Exception as e:
                    messagebox.showerror("Error", str(e))
            self.set_mode(None)

    def on_drag(self, event):
        if not self.doc: return
        c_x = self.canvas.canvasx(event.x)
        c_y = self.canvas.canvasy(event.y)

        if self.current_mode == 'redact' and self.redact_rect_id:
            self.canvas.coords(self.redact_rect_id,
                               self.redact_start_x, self.redact_start_y, c_x, c_y)
            return

        if not self.selected_item or not self.drag_mode: return
        it = self.selected_item
        dx = c_x - self.drag_start_x
        dy = c_y - self.drag_start_y

        if self.drag_mode == 'move':
            it['x'] = self.drag_item_x + dx
            it['y'] = self.drag_item_y + dy
            self.canvas.coords(it['id'], it['x'], it['y'])

        elif self.drag_mode == 'resize_SE':
            self._apply_resize(it, it['x'], it['y'],
                               max(10, self.drag_item_w+dx),
                               max(10, self.drag_item_h+dy))
        elif self.drag_mode == 'resize_NW':
            nw = max(10, self.drag_item_w-dx)
            nh = max(10, self.drag_item_h-dy)
            self._apply_resize(it,
                               self.drag_item_x+(self.drag_item_w-nw),
                               self.drag_item_y+(self.drag_item_h-nh), nw, nh)
        elif self.drag_mode == 'resize_NE':
            nw = max(10, self.drag_item_w+dx)
            nh = max(10, self.drag_item_h-dy)
            self._apply_resize(it, it['x'],
                               self.drag_item_y+(self.drag_item_h-nh), nw, nh)
        elif self.drag_mode == 'resize_SW':
            nw = max(10, self.drag_item_w-dx)
            nh = max(10, self.drag_item_h+dy)
            self._apply_resize(it,
                               self.drag_item_x+(self.drag_item_w-nw),
                               it['y'], nw, nh)
        self._draw_selection(it)

    def _apply_resize(self, item, nx, ny, nw, nh):
        item['x'], item['y'], item['w'], item['h'] = nx, ny, nw, nh
        if item['type'] == 'image':
            self._refresh_image(item)
        elif item['type'] == 'text':
            # For text: only change the wrap-width of the box.
            # Font size is controlled exclusively by the format bar.
            self._refresh_text(item)

    def on_release(self, event):
        if not self.doc: return
        c_x = self.canvas.canvasx(event.x)
        c_y = self.canvas.canvasy(event.y)

        if self.current_mode == 'redact' and self.redact_rect_id:
            px1,py1 = self._c2p(self.redact_start_x, self.redact_start_y)
            px2,py2 = self._c2p(c_x, c_y)
            r = fitz.Rect(min(px1,px2),min(py1,py2),max(px1,px2),max(py1,py2))
            self.commit_floating_items()
            page = self.doc[self.current_page_idx]
            page.add_redact_annot(r, fill=(1,1,1))
            page.apply_redactions()
            self.canvas.delete(self.redact_rect_id)
            self.redact_rect_id = None
            self.save_state(); self.render_page(); self.set_mode(None)
            return

        if self.selected_item and self.drag_mode:
            self._draw_selection(self.selected_item)
        self.drag_mode = None


if __name__ == "__main__":
    app = PDFEditor()
    app.mainloop()
