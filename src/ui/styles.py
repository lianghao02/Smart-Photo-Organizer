# -*- coding: utf-8 -*-
from tkinter import ttk

class Styles:
    @staticmethod
    def setup_styles(root):
        style = ttk.Style()
        style.theme_use('clam')
        
        # --- Color Palette ---
        BG_COLOR = "#F4F6F9"
        SECTION_BG = "#FFFFFF"
        PRIMARY_COLOR = "#4A90E2"
        TEXT_COLOR = "#2C3E50"
        ERROR_COLOR = "#E74C3C"

        # --- Fonts ---
        MAIN_FONT = ("Microsoft JhengHei UI", 10)
        BOLD_FONT = ("Microsoft JhengHei UI", 10, "bold")
        HEADER_FONT = ("Microsoft JhengHei UI", 11, "bold")

        root.configure(bg=BG_COLOR)

        # Base Styles
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=MAIN_FONT)
        style.configure("Section.TFrame", background=SECTION_BG)
        style.configure("Section.TLabel", background=SECTION_BG, foreground=TEXT_COLOR, font=MAIN_FONT)

        # LabelFrame
        style.configure("TLabelframe", background=SECTION_BG, bordercolor="#DCE1E7", borderwidth=1)
        style.configure("TLabelframe.Label", background=SECTION_BG, foreground=PRIMARY_COLOR, font=HEADER_FONT)

        # Buttons
        style.configure("TButton", 
            font=BOLD_FONT, 
            borderwidth=0, 
            focuscolor="none", 
            padding=8,
            background="#E0E6ED",
            foreground=TEXT_COLOR
        )
        style.map("TButton",
            background=[('active', PRIMARY_COLOR), ('disabled', '#D0D0D0')],
            foreground=[('active', 'white'), ('disabled', '#888888')]
        )

        style.configure("Primary.TButton", background=PRIMARY_COLOR, foreground="white")
        style.map("Primary.TButton", background=[('active', '#357ABD')])

        style.configure("Danger.TButton", background=ERROR_COLOR, foreground="white")
        style.map("Danger.TButton", background=[('active', '#C0392B')])

        # Inputs
        style.configure("TEntry", padding=5, bordercolor=PRIMARY_COLOR)
        style.configure("TCheckbutton", background=SECTION_BG, font=MAIN_FONT, focuscolor="none")
        style.configure("TRadiobutton", background=SECTION_BG, font=MAIN_FONT, focuscolor="none")
        
        # Progressbar
        style.configure("Horizontal.TProgressbar", troughcolor="#E0E0E0", background=PRIMARY_COLOR, bordercolor=BG_COLOR, lightcolor=PRIMARY_COLOR, darkcolor=PRIMARY_COLOR)
