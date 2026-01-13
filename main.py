# -*- coding: utf-8 -*-
import tkinter as tk
from src.ui.main_window import MainWindow

if __name__ == "__main__":
    root = tk.Tk()
    # Optional: Set icon if available
    # try: root.iconbitmap("assets/icon.ico")
    # except: pass
    
    app = MainWindow(root)
    root.mainloop()
