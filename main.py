import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from PIL import Image, ImageTk
import fitz  # PyMuPDF
import io

class PDFEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced PDF Editor - Movable Objects")
        self.root.geometry("1100x800")

        self.doc = None
        self.current_page_idx = 0
        self.current_mode = None  # None, 'text', 'image', 'redact', 'edit_text'
        self.zoom = 1.5

        # Undo / Redo History
        self.history = []
        self.history_idx = -1

        # Selection and floating object tracking
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        
        self.floating_items = []  # dicts: {'id': canvas_id, 'type': 'text'/'image', 'val': str_or_filepath, 'img_ref': tk_img}
        self.dragging_item = None

        self.setup_ui()

    def setup_ui(self):
        # Toolbar
        self.toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_open = tk.Button(self.toolbar, text="Open PDF", command=self.open_pdf)
        btn_open.pack(side=tk.LEFT, padx=2, pady=2)

        btn_save = tk.Button(self.toolbar, text="Save PDF", command=self.save_pdf)
        btn_save.pack(side=tk.LEFT, padx=2, pady=2)

        tk.Label(self.toolbar, text=" | ").pack(side=tk.LEFT)

        self.btn_undo = tk.Button(self.toolbar, text="Undo", command=self.undo, state=tk.DISABLED)
        self.btn_undo.pack(side=tk.LEFT, padx=2, pady=2)

        self.btn_redo = tk.Button(self.toolbar, text="Redo", command=self.redo, state=tk.DISABLED)
        self.btn_redo.pack(side=tk.LEFT, padx=2, pady=2)

        tk.Label(self.toolbar, text=" | Page:").pack(side=tk.LEFT)

        btn_prev = tk.Button(self.toolbar, text="<", command=self.prev_page)
        btn_prev.pack(side=tk.LEFT, padx=2, pady=2)

        self.lbl_page = tk.Label(self.toolbar, text="0/0")
        self.lbl_page.pack(side=tk.LEFT, padx=2)

        btn_next = tk.Button(self.toolbar, text=">", command=self.next_page)
        btn_next.pack(side=tk.LEFT, padx=2, pady=2)

        tk.Label(self.toolbar, text=" | Tools: ").pack(side=tk.LEFT)

        self.btn_add_text = tk.Button(self.toolbar, text="Add Text", command=lambda: self.set_mode('text'))
        self.btn_add_text.pack(side=tk.LEFT, padx=2, pady=2)
        
        self.btn_edit_text = tk.Button(self.toolbar, text="Edit Existing Text", command=lambda: self.set_mode('edit_text'))
        self.btn_edit_text.pack(side=tk.LEFT, padx=2, pady=2)

        self.btn_img = tk.Button(self.toolbar, text="Insert Image", command=lambda: self.set_mode('image'))
        self.btn_img.pack(side=tk.LEFT, padx=2, pady=2)

        self.btn_redact = tk.Button(self.toolbar, text="Remove/Redact", command=lambda: self.set_mode('redact'))
        self.btn_redact.pack(side=tk.LEFT, padx=2, pady=2)
        
        # Add a manual commit button
        self.btn_commit = tk.Button(self.toolbar, text="Commit Floating Objects", command=self.commit_floating_items, fg="green")
        self.btn_commit.pack(side=tk.LEFT, padx=10, pady=2)

        self.lbl_mode = tk.Label(self.toolbar, text="Current Mode: View", fg="blue")
        self.lbl_mode.pack(side=tk.RIGHT, padx=10)

        # Canvas for PDF
        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="gray")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.scrollbar_y = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.scrollbar_x = tk.Scrollbar(self.root, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas.configure(yscrollcommand=self.scrollbar_y.set, xscrollcommand=self.scrollbar_x.set)

        # Bindings
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)

    def set_mode(self, mode):
        self.current_mode = mode
        if mode == 'text':
            self.lbl_mode.config(text="Mode: Click to Add Movable Text")
        elif mode == 'edit_text':
            self.lbl_mode.config(text="Mode: Click Existing Text to Edit")
        elif mode == 'image':
            self.lbl_mode.config(text="Mode: Click to Insert Movable Image")
        elif mode == 'redact':
            self.lbl_mode.config(text="Mode: Drag to Remove/Redact Context")
        else:
            self.lbl_mode.config(text="Mode: View / Drag Objects")

    def open_pdf(self):
        filepath = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if filepath:
            self.doc = fitz.open(filepath)
            self.current_page_idx = 0
            
            self.history = []
            self.history_idx = -1
            self.save_state()
            
            self.render_page()

    def save_pdf(self):
        if not self.doc:
            return
        self.commit_floating_items()
        filepath = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if filepath:
            self.doc.save(filepath)
            messagebox.showinfo("Success", "PDF saved successfully!")

    # --- History & State Tracking ---
    def save_state(self):
        if not self.doc: return
        if self.history_idx < len(self.history) - 1:
            self.history = self.history[:self.history_idx+1]
        
        state_bytes = self.doc.write()
        self.history.append(state_bytes)
        self.history_idx += 1
        self.update_history_buttons()

    def load_state(self, index):
        if 0 <= index < len(self.history):
            self.history_idx = index
            self.doc = fitz.open("pdf", self.history[index])
            self.update_history_buttons()
            self.render_page()

    def undo(self):
        self.commit_floating_items()
        if self.history_idx > 0:
            self.load_state(self.history_idx - 1)

    def redo(self):
        self.commit_floating_items()
        if self.history_idx < len(self.history) - 1:
            self.load_state(self.history_idx + 1)

    def update_history_buttons(self):
        self.btn_undo.config(state=tk.NORMAL if self.history_idx > 0 else tk.DISABLED)
        self.btn_redo.config(state=tk.NORMAL if self.history_idx < len(self.history) - 1 else tk.DISABLED)

    # --- Navigation ---
    def prev_page(self):
        self.commit_floating_items()
        if self.doc and self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.render_page()

    def next_page(self):
        self.commit_floating_items()
        if self.doc and self.current_page_idx < len(self.doc) - 1:
            self.current_page_idx += 1
            self.render_page()

    def render_page(self):
        if not self.doc:
            return
            
        # Clean up floating items on render
        for item in self.floating_items:
            self.canvas.delete(item['id'])
        self.floating_items = []

        page = self.doc[self.current_page_idx]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)

        img_data = pix.tobytes("ppm")
        image = Image.open(io.BytesIO(img_data))
        self.tk_image = ImageTk.PhotoImage(image)

        self.canvas.delete("all")
        # Tag the background image as 'bg' so we don't drag it
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image, tags="bg")
        self.canvas.config(scrollregion=self.canvas.bbox(tk.ALL))

        self.lbl_page.config(text=f"{self.current_page_idx + 1}/{len(self.doc)}")

    def get_pdf_coords(self, x, y):
        x_pdf = x / self.zoom
        y_pdf = y / self.zoom
        return x_pdf, y_pdf

    # --- Floating Object Commit ---
    def commit_floating_items(self):
        if not self.doc or not self.floating_items:
            return
            
        page = self.doc[self.current_page_idx]
        
        for item in self.floating_items:
            coords = self.canvas.coords(item['id'])
            if not coords: continue
            
            x_canv, y_canv = coords[0], coords[1]
            pdf_x, pdf_y = self.get_pdf_coords(x_canv, y_canv)
            
            if item['type'] == 'text':
                # Insert text at the anchor point
                p = fitz.Point(pdf_x, pdf_y)
                # Using size 18 on canvas looks like size 12 on pdf zoomed at 1.5
                page.insert_text(p, item['val'], fontsize=12, color=(0,0,0))
            
            elif item['type'] == 'image':
                # Calculate image rect based on tk image dimensions
                img_w = item['img_ref'].width()
                img_h = item['img_ref'].height()
                pdf_w = img_w / self.zoom
                pdf_h = img_h / self.zoom
                
                rect = fitz.Rect(pdf_x, pdf_y, pdf_x + pdf_w, pdf_y + pdf_h)
                page.insert_image(rect, filename=item['val'])
                
        self.save_state()
        self.render_page()

    # --- Tool Actions ---
    def on_canvas_click(self, event):
        if not self.doc:
            return

        c_x = self.canvas.canvasx(event.x)
        c_y = self.canvas.canvasy(event.y)
        pdf_x, pdf_y = self.get_pdf_coords(c_x, c_y)
        page = self.doc[self.current_page_idx]

        # Check if we clicked on a floating object to drag it (in View mode or any mode)
        # except redact where we want to draw a box
        if self.current_mode != 'redact':
            item = self.canvas.find_withtag(tk.CURRENT)
            if item and "bg" not in self.canvas.gettags(item[0]):
                self.dragging_item = item[0]
                self.start_x = c_x
                self.start_y = c_y
                return

        if self.current_mode == 'text':
            text = simpledialog.askstring("Input", "Enter text:")
            if text:
                # Spawn floating text
                t_id = self.canvas.create_text(c_x, c_y, text=text, fill="black", font=("Arial", int(12*self.zoom)), anchor=tk.NW, tags="floating")
                self.floating_items.append({'id': t_id, 'type': 'text', 'val': text, 'img_ref': None})
                self.set_mode(None)
                
        elif self.current_mode == 'edit_text':
            blocks = page.get_text("blocks")
            clicked_block = None
            for b in blocks:
                r = fitz.Rect(b[:4])
                if r.contains(fitz.Point(pdf_x, pdf_y)):
                    clicked_block = b
                    break
                    
            if clicked_block:
                old_text = clicked_block[4].strip()
                new_text = simpledialog.askstring("Edit Text", f"Original: {old_text}\n\nEnter replacement:", initialvalue=old_text)
                if new_text is not None and new_text != old_text:
                    b_rect = fitz.Rect(clicked_block[:4])
                    
                    page.add_redact_annot(b_rect, fill=(1,1,1))
                    page.apply_redactions()
                    
                    # Convert PDF coords back to canvas coords for the floating text
                    fc_x = clicked_block[0] * self.zoom
                    fc_y = clicked_block[1] * self.zoom
                    
                    t_id = self.canvas.create_text(fc_x, fc_y, text=new_text, fill="black", font=("Arial", int(12*self.zoom)), anchor=tk.NW, tags="floating")
                    self.floating_items.append({'id': t_id, 'type': 'text', 'val': new_text, 'img_ref': None})
                    self.save_state() # save the redaction
            else:
                messagebox.showinfo("No Text Found", "Could not identify text at that location.")
            self.set_mode(None)

        elif self.current_mode == 'image':
            filepath = filedialog.askopenfilename(filetypes=[("Image files", "*.png;*.jpg;*.jpeg")])
            if filepath:
                try:
                    with Image.open(filepath) as img:
                        w, h = img.size
                    max_dim = 150.0
                    if w > max_dim or h > max_dim:
                        ratio = min(max_dim/w, max_dim/h)
                        new_w, new_h = w * ratio, h * ratio
                    else:
                        new_w, new_h = w, h
                        
                    # Resize for Tkinter canvas display
                    img_resized = Image.open(filepath).resize((int(new_w * self.zoom), int(new_h * self.zoom)), Image.Resampling.LANCZOS)
                    tk_img = ImageTk.PhotoImage(img_resized)
                    
                    i_id = self.canvas.create_image(c_x, c_y, anchor=tk.NW, image=tk_img, tags="floating")
                    self.floating_items.append({'id': i_id, 'type': 'image', 'val': filepath, 'img_ref': tk_img})
                except Exception as e:
                    messagebox.showerror("Error", f"Could not insert image: {e}")
                self.set_mode(None)
                
        elif self.current_mode == 'redact':
            self.start_x = c_x
            self.start_y = c_y
            self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', fill='red', stipple='gray50')

    def on_canvas_drag(self, event):
        c_x = self.canvas.canvasx(event.x)
        c_y = self.canvas.canvasy(event.y)
        
        if self.dragging_item:
            dx = c_x - self.start_x
            dy = c_y - self.start_y
            self.canvas.move(self.dragging_item, dx, dy)
            self.start_x = c_x
            self.start_y = c_y
            
        elif self.current_mode == 'redact' and self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, c_x, c_y)

    def on_canvas_release(self, event):
        if self.dragging_item:
            self.dragging_item = None
            
        elif self.current_mode == 'redact' and self.rect_id:
            c_x = self.canvas.canvasx(event.x)
            c_y = self.canvas.canvasy(event.y)
            
            pdf_x1, pdf_y1 = self.get_pdf_coords(self.start_x, self.start_y)
            pdf_x2, pdf_y2 = self.get_pdf_coords(c_x, c_y)

            page = self.doc[self.current_page_idx]
            r = fitz.Rect(min(pdf_x1, pdf_x2), min(pdf_y1, pdf_y2), max(pdf_x1, pdf_x2), max(pdf_y1, pdf_y2))
            
            self.commit_floating_items() # Commit any pending objects first
            
            page.add_redact_annot(r, fill=(1,1,1))
            page.apply_redactions()
            
            self.canvas.delete(self.rect_id)
            self.rect_id = None
            
            self.save_state()
            self.render_page()
            self.set_mode(None)

if __name__ == "__main__":
    root = tk.Tk()
    app = PDFEditor(root)
    root.mainloop()
