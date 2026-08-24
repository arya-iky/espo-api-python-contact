"""
EspoCRM Contact Manager
============================================================

Relational Data Dashboard

FITUR
------------------------------------------------------------
CONTACT
- Menampilkan daftar Contact
- Search Contact
- Pagination Contact
- Detail Contact
- Add Contact
- Edit Contact
- Delete Contact
- Restore / Undo Delete
- Export CSV
- Refresh Data

RELATIONSHIP
- Contact
- Contact -> Account
- Contact -> Opportunity
- Contact -> Case
- Search Relationship
- Relationship Cache
- Relationship Count

KEYBOARD SHORTCUT
------------------------------------------------------------
F5          = Refresh Data
Ctrl + F    = Focus Search Contact
Ctrl + Z    = Restore Contact terakhir yang dihapus
Escape      = Kembali ke Detail Contact

API
------------------------------------------------------------
File ini menggunakan fungsi dari api.py:

CONTACT
- get_contacts()
- get_contact()
- create_contact()
- delete_contact()

RELATIONSHIP
- get_contact_accounts()
- get_contact_opportunities()
- get_contact_cases()
- get_relationship_summary()

UI
------------------------------------------------------------
Tkinter + ttk
"""

import csv
import inspect
import tkinter as tk

from tkinter import ttk, messagebox, filedialog

import api


# ============================================================
# OPTIONAL CONTACT FORM
# ============================================================

try:
    from contact_form import ContactForm
except ImportError:
    ContactForm = None


# ============================================================
# DASHBOARD
# ============================================================

class Dashboard:

    # ========================================================
    # COLORS
    # ========================================================

    BG = "#F4F6F9"

    SIDEBAR = "#172033"
    SIDEBAR_HOVER = "#24304A"

    ACTIVE = "#3B82F6"
    BLUE_DARK = "#2563EB"

    WHITE = "#FFFFFF"

    TEXT = "#172033"
    MUTED = "#6B7280"
    BORDER = "#E5E7EB"

    GREEN = "#10B981"
    RED = "#EF4444"
    ORANGE = "#F59E0B"
    PURPLE = "#8B5CF6"

    LIGHT_BLUE = "#E8F1FF"
    LIGHT_GRAY = "#F8FAFC"

    # ========================================================
    # SETTINGS
    # ========================================================

    PAGE_SIZE = 5

    RELATION_PAGE_SIZE = 100

    SEARCH_DELAY = 350

    RELATION_SEARCH_DELAY = 250

    # ========================================================
    # RELATIONSHIP CONFIGURATION
    # ========================================================

    RELATIONS = {

        "contact": (
            "Kontak",
            "Contact",
            None
        ),

        "accounts": (
            "Accounts",
            "Account",
            "get_contact_accounts"
        ),

        "opportunities": (
            "Opportunities",
            "Opportunity",
            "get_contact_opportunities"
        ),

        "cases": (
            "Cases",
            "Case",
            "get_contact_cases"
        ),
    }

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):

        self.root = tk.Tk()

        self.root.title(
            "EspoCRM Contact Manager"
        )

        self.root.geometry(
            "1400x800"
        )

        self.root.minsize(
            1150,
            680
        )

        self.root.configure(
            bg=self.BG
        )

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.action_exit
        )

        # ====================================================
        # DATA STATE
        # ====================================================

        self.all_contacts = []

        self.current_contact = None

        self.current_relation = None

        self.relation_cache = {}

        # ====================================================
        # DELETE / RESTORE
        # ====================================================

        self.deleted_contacts = []

        # ====================================================
        # PAGINATION
        # ====================================================

        self.current_offset = 0

        self.current_page = 1

        self.total_contacts = 0

        # ====================================================
        # SEARCH
        # ====================================================

        self.search_placeholder = (
            "Search contact..."
        )

        self.relation_search_placeholder = (
            "Search relationship..."
        )

        self.search_after_id = None

        self.relation_search_after_id = None

        # ====================================================
        # STATE CONTROL
        # ====================================================

        self._loading = False

        self._closing = False

        # ====================================================
        # BUILD
        # ====================================================

        self.setup_styles()

        self.build_ui()

        # ====================================================
        # KEYBOARD SHORTCUT
        # ====================================================

        self.root.bind(
            "<F5>",
            self.shortcut_refresh
        )

        self.root.bind(
            "<Escape>",
            self.shortcut_escape
        )

        self.root.bind(
            "<Control-f>",
            self.shortcut_search
        )

        self.root.bind(
            "<Control-z>",
            self.action_restore
        )

        # ====================================================
        # CENTER WINDOW
        # ====================================================

        self.center_window(
            1400,
            800
        )

        # ====================================================
        # INITIAL LOAD
        # ====================================================

        self.root.after(
            50,
            self.load_data
        )

        self.root.mainloop()

    # ========================================================
    # KEYBOARD SHORTCUT
    # ========================================================

    def shortcut_refresh(
        self,
        event=None
    ):

        self.load_data()

        return "break"

    # --------------------------------------------------------

    def shortcut_escape(
        self,
        event=None
    ):

        self.show_contact_details()

        return "break"

    # --------------------------------------------------------

    def shortcut_search(
        self,
        event=None
    ):

        self.focus_contact_search()

        return "break"

    # ========================================================
    # WINDOW
    # ========================================================

    def center_window(
        self,
        width,
        height
    ):

        self.root.update_idletasks()

        screen_width = (
            self.root.winfo_screenwidth()
        )

        screen_height = (
            self.root.winfo_screenheight()
        )

        x = max(
            (screen_width - width) // 2,
            0
        )

        y = max(
            (screen_height - height) // 2,
            0
        )

        self.root.geometry(
            f"{width}x{height}+{x}+{y}"
        )

    # ========================================================
    # STYLES
    # ========================================================

    def setup_styles(
        self
    ):

        style = ttk.Style(
            self.root
        )

        if "clam" in style.theme_names():

            style.theme_use(
                "clam"
            )

        # ----------------------------------------------------
        # TREEVIEW
        # ----------------------------------------------------

        style.configure(
            "Modern.Treeview",
            background=self.WHITE,
            fieldbackground=self.WHITE,
            foreground=self.TEXT,
            rowheight=38,
            font=("Segoe UI", 10),
            borderwidth=0
        )

        style.map(
            "Modern.Treeview",
            background=[
                (
                    "selected",
                    self.LIGHT_BLUE
                )
            ],
            foreground=[
                (
                    "selected",
                    self.TEXT
                )
            ]
        )

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        style.configure(
            "Modern.Treeview.Heading",
            background="#F8FAFC",
            foreground="#64748B",
            font=("Segoe UI", 9, "bold"),
            padding=8
        )

        # ----------------------------------------------------
        # PRIMARY BUTTON
        # ----------------------------------------------------

        style.configure(
            "Primary.TButton",
            background=self.ACTIVE,
            foreground=self.WHITE,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7)
        )

        style.map(
            "Primary.TButton",
            background=[
                (
                    "active",
                    self.BLUE_DARK
                )
            ],
            foreground=[
                (
                    "active",
                    self.WHITE
                )
            ]
        )

        # ----------------------------------------------------
        # SECONDARY BUTTON
        # ----------------------------------------------------

        style.configure(
            "Secondary.TButton",
            background=self.WHITE,
            foreground=self.TEXT,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7)
        )

        style.map(
            "Secondary.TButton",
            background=[
                (
                    "active",
                    "#F1F5F9"
                )
            ]
        )

        # ----------------------------------------------------
        # DANGER BUTTON
        # ----------------------------------------------------

        style.configure(
            "Danger.TButton",
            background=self.WHITE,
            foreground=self.RED,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7)
        )

        style.map(
            "Danger.TButton",
            background=[
                (
                    "active",
                    "#FEF2F2"
                )
            ]
        )

        # ----------------------------------------------------
        # RESTORE BUTTON
        # ----------------------------------------------------

        style.configure(
            "Restore.TButton",
            background=self.WHITE,
            foreground=self.GREEN,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7)
        )

        style.map(
            "Restore.TButton",
            background=[
                (
                    "active",
                    "#ECFDF5"
                )
            ]
        )

    # ========================================================
    # BUILD UI
    # ========================================================

    def build_ui(
        self
    ):

        self.build_sidebar()

        main = tk.Frame(
            self.root,
            bg=self.BG
        )

        main.pack(
            side="left",
            fill="both",
            expand=True
        )

        self.build_header(
            main
        )

        self.build_stats(
            main
        )

        self.build_content(
            main
        )

        self.build_bottom_bar(
            main
        )

    # ========================================================
    # SIDEBAR
    # ========================================================

    def build_sidebar(
        self
    ):

        side = tk.Frame(
            self.root,
            bg=self.SIDEBAR,
            width=250
        )

        side.pack(
            side="left",
            fill="y"
        )

        side.pack_propagate(
            False
        )

        # ----------------------------------------------------
        # BRAND
        # ----------------------------------------------------

        brand = tk.Frame(
            side,
            bg=self.SIDEBAR
        )

        brand.pack(
            fill="x",
            padx=22,
            pady=(28, 25)
        )

        tk.Label(
            brand,
            text="E",
            bg=self.ACTIVE,
            fg=self.WHITE,
            font=("Segoe UI", 20, "bold"),
            width=2
        ).pack(
            side="left"
        )

        btxt = tk.Frame(
            brand,
            bg=self.SIDEBAR
        )

        btxt.pack(
            side="left",
            padx=12
        )

        tk.Label(
            btxt,
            text="EspoCRM",
            bg=self.SIDEBAR,
            fg=self.WHITE,
            font=("Segoe UI", 14, "bold")
        ).pack(
            anchor="w"
        )

        tk.Label(
            btxt,
            text="Relational Data",
            bg=self.SIDEBAR,
            fg="#94A3B8",
            font=("Segoe UI", 8)
        ).pack(
            anchor="w"
        )

        # ----------------------------------------------------
        # NAVIGATION
        # ----------------------------------------------------

        tk.Label(
            side,
            text="NAVIGATION",
            bg=self.SIDEBAR,
            fg="#64748B",
            font=("Segoe UI", 8, "bold")
        ).pack(
            anchor="w",
            padx=28,
            pady=(8, 10)
        )

        self.nav_button(
            side,
            "▦   Contacts",
            self.show_contact_details,
            True
        )

        self.nav_button(
            side,
            "+   Add Contact",
            self.action_add
        )

        self.nav_button(
            side,
            "↻   Refresh Data",
            self.load_data
        )

        self.nav_button(
            side,
            "⇩   Export CSV",
            self.action_export
        )

        # ----------------------------------------------------
        # SEPARATOR
        # ----------------------------------------------------

        tk.Frame(
            side,
            bg="#26324A",
            height=1
        ).pack(
            fill="x",
            padx=22,
            pady=(28, 18)
        )

        # ----------------------------------------------------
        # API STATUS
        # ----------------------------------------------------

        status = tk.Frame(
            side,
            bg=self.SIDEBAR
        )

        status.pack(
            side="bottom",
            fill="x",
            padx=25,
            pady=25
        )

        tk.Label(
            status,
            text="ESPOCRM API",
            bg=self.SIDEBAR,
            fg="#94A3B8",
            font=("Segoe UI", 8)
        ).pack(
            anchor="w"
        )

        self.api_status = tk.Label(
            status,
            text="● Connecting...",
            bg=self.SIDEBAR,
            fg=self.ORANGE,
            font=("Segoe UI", 9, "bold")
        )

        self.api_status.pack(
            anchor="w",
            pady=(5, 0)
        )

    # ========================================================
    # NAV BUTTON
    # ========================================================

    def nav_button(
        self,
        parent,
        text,
        command,
        active=False
    ):

        btn = tk.Button(
            parent,
            text=text,
            anchor="w",
            relief="flat",
            bd=0,
            bg=(
                self.ACTIVE
                if active
                else self.SIDEBAR
            ),
            fg=(
                self.WHITE
                if active
                else "#CBD5E1"
            ),
            activebackground=(
                self.ACTIVE
                if active
                else self.SIDEBAR_HOVER
            ),
            activeforeground=self.WHITE,
            font=(
                "Segoe UI",
                10,
                "bold" if active else "normal"
            ),
            padx=18,
            pady=13,
            command=command,
            cursor="hand2"
        )

        btn.pack(
            fill="x",
            padx=14,
            pady=(
                0 if active else 2,
                0
            )
        )

        return btn

    # ========================================================
    # HEADER
    # ========================================================

    def build_header(
        self,
        parent
    ):

        header = tk.Frame(
            parent,
            bg=self.WHITE,
            height=90
        )

        header.pack(
            fill="x"
        )

        header.pack_propagate(
            False
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        title = tk.Frame(
            header,
            bg=self.WHITE
        )

        title.pack(
            side="left",
            padx=34,
            pady=17
        )

        tk.Label(
            title,
            text="Contacts",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 25, "bold")
        ).pack(
            anchor="w"
        )

        tk.Label(
            title,
            text="CRM / Relational Data",
            bg=self.WHITE,
            fg=self.MUTED,
            font=("Segoe UI", 9)
        ).pack(
            anchor="w"
        )

        # ----------------------------------------------------
        # SEARCH
        # ----------------------------------------------------

        box = tk.Frame(
            header,
            bg="#F1F5F9",
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        box.pack(
            side="right",
            padx=28,
            pady=22
        )

        tk.Label(
            box,
            text="⌕",
            bg="#F1F5F9",
            fg="#94A3B8",
            font=("Segoe UI", 13)
        ).pack(
            side="left",
            padx=(10, 3)
        )

        self.search_var = tk.StringVar()

        self.search_entry = tk.Entry(
            box,
            textvariable=self.search_var,
            bg="#F1F5F9",
            fg="#94A3B8",
            relief="flat",
            width=28,
            font=("Segoe UI", 10),
            insertbackground=self.TEXT
        )

        self.search_entry.pack(
            side="left",
            ipady=7,
            padx=(0, 10)
        )

        self.search_entry.insert(
            0,
            self.search_placeholder
        )

        self.search_entry.bind(
            "<FocusIn>",
            self.search_focus_in
        )

        self.search_entry.bind(
            "<FocusOut>",
            self.search_focus_out
        )

        self.search_entry.bind(
            "<KeyRelease>",
            self.search_contacts
        )

    # ========================================================
    # STATS
    # ========================================================

    def build_stats(
        self,
        parent
    ):

        bar = tk.Frame(
            parent,
            bg=self.BG
        )

        bar.pack(
            fill="x",
            padx=28,
            pady=(18, 16)
        )

        self.stat_total = self.stat_card(
            bar,
            "C",
            "TOTAL CONTACTS",
            self.ACTIVE
        )

        self.stat_visible = self.stat_card(
            bar,
            "V",
            "VISIBLE RESULTS",
            self.GREEN
        )

        self.stat_accounts = self.stat_card(
            bar,
            "A",
            "ACCOUNTS",
            self.ORANGE
        )

        self.stat_opportunities = self.stat_card(
            bar,
            "O",
            "OPPORTUNITIES",
            self.PURPLE
        )

        self.stat_cases = self.stat_card(
            bar,
            "K",
            "CASES",
            self.RED
        )

        for card in (
            self.stat_total,
            self.stat_visible,
            self.stat_accounts,
            self.stat_opportunities,
            self.stat_cases
        ):

            card.pack(
                side="left",
                fill="x",
                expand=True,
                padx=4
            )

    # ========================================================
    # STAT CARD
    # ========================================================

    def stat_card(
        self,
        parent,
        icon,
        title,
        color
    ):

        frame = tk.Frame(
            parent,
            bg=self.WHITE,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            height=82
        )

        frame.pack_propagate(
            False
        )

        tk.Label(
            frame,
            text=icon,
            bg=color,
            fg=self.WHITE,
            font=("Segoe UI", 15, "bold"),
            width=2
        ).pack(
            side="left",
            padx=(14, 12),
            pady=17
        )

        txt = tk.Frame(
            frame,
            bg=self.WHITE
        )

        txt.pack(
            side="left",
            fill="both",
            expand=True,
            pady=12
        )

        tk.Label(
            txt,
            text=title,
            bg=self.WHITE,
            fg="#64748B",
            font=("Segoe UI", 8, "bold")
        ).pack(
            anchor="w"
        )

        value = tk.Label(
            txt,
            text="0",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 17, "bold")
        )

        value.pack(
            anchor="w",
            pady=(3, 0)
        )

        frame.value = value

        return frame

    # ========================================================
    # CONTENT
    # ========================================================

    def build_content(
        self,
        parent
    ):

        content = tk.Frame(
            parent,
            bg=self.BG
        )

        content.pack(
            fill="both",
            expand=True,
            padx=28
        )

        content.columnconfigure(
            0,
            weight=7
        )

        content.columnconfigure(
            1,
            weight=3
        )

        content.rowconfigure(
            0,
            weight=1
        )

        self.build_contact_table(
            content
        )

        self.build_detail_panel(
            content
        )

    # ========================================================
    # CONTACT TABLE
    # ========================================================

    def build_contact_table(
        self,
        parent
    ):

        outer = tk.Frame(
            parent,
            bg=self.WHITE,
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        outer.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 10)
        )

        # ----------------------------------------------------
        # TABLE HEADER
        # ----------------------------------------------------

        top = tk.Frame(
            outer,
            bg=self.WHITE
        )

        top.pack(
            fill="x",
            padx=16,
            pady=(14, 8)
        )

        tk.Label(
            top,
            text="Contact List",
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 11, "bold")
        ).pack(
            side="left"
        )

        self.result_label = tk.Label(
            top,
            text="0 result(s)",
            bg=self.WHITE,
            fg=self.MUTED,
            font=("Segoe UI", 9)
        )

        self.result_label.pack(
            side="left",
            padx=10
        )

        # ----------------------------------------------------
        # TABLE
        # ----------------------------------------------------

        table = tk.Frame(
            outer,
            bg=self.WHITE
        )

        table.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=(0, 10)
        )

        columns = (
            "ID",
            "Nama",
            "Email",
            "Telepon",
            "Account",
            "Created At"
        )

        self.tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            style="Modern.Treeview",
            selectmode="browse"
        )

        ybar = ttk.Scrollbar(
            table,
            orient="vertical",
            command=self.tree.yview
        )

        xbar = ttk.Scrollbar(
            table,
            orient="horizontal",
            command=self.tree.xview
        )

        self.tree.configure(
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set
        )

        widths = {
            "ID": 150,
            "Nama": 145,
            "Email": 210,
            "Telepon": 145,
            "Account": 180,
            "Created At": 160
        }

        for col in columns:

            self.tree.heading(
                col,
                text=col
            )

            self.tree.column(
                col,
                width=widths[col],
                minwidth=90,
                stretch=False
            )

        self.tree.bind(
            "<<TreeviewSelect>>",
            self.on_contact_select
        )

        self.tree.bind(
            "<Double-1>",
            lambda event:
            self.action_edit()
        )

        self.tree.pack(
            side="left",
            fill="both",
            expand=True
        )

        ybar.pack(
            side="right",
            fill="y"
        )

        xbar.pack(
            side="bottom",
            fill="x"
        )

        # ----------------------------------------------------
        # PAGINATION
        # ----------------------------------------------------

        nav = tk.Frame(
            outer,
            bg=self.WHITE
        )

        nav.pack(
            fill="x",
            padx=18,
            pady=(0, 14)
        )

        self.previous_button = ttk.Button(
            nav,
            text="‹ Previous",
            style="Secondary.TButton",
            command=self.previous_page
        )

        self.previous_button.pack(
            side="left"
        )

        self.page_label = tk.Label(
            nav,
            text="Page 1 / 1",
            bg=self.WHITE,
            fg=self.MUTED,
            font=("Segoe UI", 9)
        )

        self.page_label.pack(
            side="left",
            padx=18
        )

        self.next_button = ttk.Button(
            nav,
            text="Next ›",
            style="Secondary.TButton",
            command=self.next_page
        )

        self.next_button.pack(
            side="left"
        )

    # ========================================================
    # DETAIL PANEL
    # ========================================================

    def build_detail_panel(
        self,
        parent
    ):

        outer = tk.Frame(
            parent,
            bg=self.WHITE,
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        outer.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        canvas = tk.Canvas(
            outer,
            bg=self.WHITE,
            highlightthickness=0
        )

        scrollbar = ttk.Scrollbar(
            outer,
            orient="vertical",
            command=canvas.yview
        )

        canvas.configure(
            yscrollcommand=scrollbar.set
        )

        canvas.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.detail_frame = tk.Frame(
            canvas,
            bg=self.WHITE
        )

        self.detail_window = canvas.create_window(
            (0, 0),
            window=self.detail_frame,
            anchor="nw"
        )

        self.detail_canvas = canvas

        self.detail_frame.bind(
            "<Configure>",
            lambda event:
            canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.bind(
            "<Configure>",
            lambda event:
            canvas.itemconfigure(
                self.detail_window,
                width=event.width
            )
        )

        # ----------------------------------------------------
        # RELATIONSHIP BAR
        # ----------------------------------------------------

        self.relationship_bar = tk.Frame(
            self.detail_frame,
            bg=self.WHITE
        )

        self.relationship_bar.pack(
            fill="x",
            padx=18,
            pady=(18, 10)
        )

        self.build_relationship_bar()

        # ----------------------------------------------------
        # DYNAMIC DETAIL
        # ----------------------------------------------------

        self.dynamic_detail = tk.Frame(
            self.detail_frame,
            bg=self.WHITE
        )

        self.dynamic_detail.pack(
            fill="both",
            expand=True
        )

        self.show_contact_details()

    # ========================================================
    # RELATIONSHIP BAR
    # ========================================================

    def build_relationship_bar(
        self
    ):

        tk.Label(
            self.relationship_bar,
            text="RELATIONSHIPS",
            bg=self.WHITE,
            fg=self.ACTIVE,
            font=("Segoe UI", 8, "bold")
        ).pack(
            anchor="w",
            pady=(0, 8)
        )

        row = tk.Frame(
            self.relationship_bar,
            bg=self.WHITE
        )

        row.pack(
            fill="x"
        )

        self.relation_buttons = {}

        for key, (
            label,
            _,
            _
        ) in self.RELATIONS.items():

            btn = tk.Button(
                row,
                text=label,
                relief="solid",
                bd=1,
                bg=self.WHITE,
                fg=self.TEXT,
                activebackground=self.ACTIVE,
                activeforeground=self.WHITE,
                font=("Segoe UI", 8, "bold"),
                padx=5,
                pady=6,
                cursor="hand2",
                command=lambda k=key:
                self.load_relationship(k)
            )

            btn.pack(
                side="left",
                fill="x",
                expand=True,
                padx=2
            )

            self.relation_buttons[key] = btn

        # ----------------------------------------------------
        # RELATION SEARCH
        # ----------------------------------------------------

        search = tk.Frame(
            self.relationship_bar,
            bg="#F1F5F9",
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        search.pack(
            fill="x",
            pady=(8, 0)
        )

        tk.Label(
            search,
            text="⌕",
            bg="#F1F5F9",
            fg="#94A3B8",
            font=("Segoe UI", 10)
        ).pack(
            side="left",
            padx=(8, 2)
        )

        self.relation_search_var = tk.StringVar()

        self.relation_search_entry = tk.Entry(
            search,
            textvariable=self.relation_search_var,
            bg="#F1F5F9",
            fg="#94A3B8",
            relief="flat",
            font=("Segoe UI", 8)
        )

        self.relation_search_entry.pack(
            side="left",
            fill="x",
            expand=True,
            ipady=6,
            padx=(0, 8)
        )

        self.relation_search_entry.insert(
            0,
            self.relation_search_placeholder
        )

        self.relation_search_entry.bind(
            "<FocusIn>",
            self.relation_search_focus_in
        )

        self.relation_search_entry.bind(
            "<FocusOut>",
            self.relation_search_focus_out
        )

        self.relation_search_entry.bind(
            "<KeyRelease>",
            self.filter_relationship
        )

    # ========================================================
    # BOTTOM BAR
    # ========================================================

    def build_bottom_bar(
        self,
        parent
    ):

        bar = tk.Frame(
            parent,
            bg=self.BG
        )

        bar.pack(
            fill="x",
            padx=28,
            pady=(12, 12)
        )

        ttk.Button(
            bar,
            text="↻ Refresh",
            style="Secondary.TButton",
            command=self.load_data
        ).pack(
            side="left",
            padx=(0, 8)
        )

        ttk.Button(
            bar,
            text="+ Add Contact",
            style="Primary.TButton",
            command=self.action_add
        ).pack(
            side="left",
            padx=4
        )

        ttk.Button(
            bar,
            text="✎ Edit",
            style="Secondary.TButton",
            command=self.action_edit
        ).pack(
            side="left",
            padx=4
        )

        ttk.Button(
            bar,
            text="✕ Delete",
            style="Danger.TButton",
            command=self.action_delete
        ).pack(
            side="left",
            padx=4
        )

        self.restore_button = ttk.Button(
            bar,
            text="↶ Restore",
            style="Restore.TButton",
            command=self.action_restore
        )

        self.restore_button.pack(
            side="left",
            padx=4
        )

        ttk.Button(
            bar,
            text="⇩ Export CSV",
            style="Secondary.TButton",
            command=self.action_export
        ).pack(
            side="right",
            padx=4
        )

        ttk.Button(
            bar,
            text="Exit",
            style="Secondary.TButton",
            command=self.action_exit
        ).pack(
            side="right",
            padx=(4, 0)
        )

        self.update_restore_button()

    # ========================================================
    # API FUNCTION COMPATIBILITY
    # ========================================================

    @staticmethod
    def function_accepts(
        function,
        parameter_name
    ):

        try:

            signature = inspect.signature(
                function
            )

        except (
            TypeError,
            ValueError
        ):

            return False

        parameters = signature.parameters

        if parameter_name in parameters:

            return True

        return any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter
            in parameters.values()
        )

    # ========================================================
    # GET CONTACTS
    # ========================================================

    def call_get_contacts(
        self,
        offset,
        max_size,
        search
    ):

        function = getattr(
            api,
            "get_contacts",
            None
        )

        if function is None:

            raise AttributeError(
                "Fungsi get_contacts() "
                "tidak ditemukan di api.py."
            )

        kwargs = {}

        if self.function_accepts(
            function,
            "offset"
        ):

            kwargs["offset"] = offset

        if self.function_accepts(
            function,
            "max_size"
        ):

            kwargs["max_size"] = max_size

        if self.function_accepts(
            function,
            "search"
        ):

            kwargs["search"] = search

        try:

            return function(
                **kwargs
            )

        except TypeError as first_error:

            # ------------------------------------------------
            # FALLBACK API LAMA
            # ------------------------------------------------

            attempts = [

                lambda:
                function(
                    offset,
                    max_size,
                    search
                ),

                lambda:
                function(
                    offset,
                    max_size
                ),

                lambda:
                function()
            ]

            last_error = first_error

            for attempt in attempts:

                try:

                    return attempt()

                except TypeError as exc:

                    last_error = exc

            raise last_error

    # ========================================================
    # RELATIONSHIP API
    # ========================================================

    def call_relation_loader(
        self,
        loader,
        contact_id
    ):

        if self.function_accepts(
            loader,
            "max_size"
        ):

            return loader(
                contact_id,
                max_size=self.RELATION_PAGE_SIZE
            )

        return loader(
            contact_id
        )

    # ========================================================
    # NORMALIZE API RESPONSE
    # ========================================================

    @staticmethod
    def normalize_response(
        data
    ):

        if isinstance(
            data,
            dict
        ):

            records = data.get(
                "list",
                []
            )

            if not isinstance(
                records,
                list
            ):

                records = []

            total = data.get(
                "total",
                len(records)
            )

            try:

                total = int(
                    total or 0
                )

            except (
                TypeError,
                ValueError
            ):

                total = len(records)

            return (
                records,
                total
            )

        if isinstance(
            data,
            list
        ):

            return (
                data,
                len(data)
            )

        return (
            [],
            0
        )

    # ========================================================
    # LOAD DATA
    # ========================================================

    def load_data(
        self,
        preserve_page=False
    ):

        if (
            self._closing
            or self._loading
        ):

            return

        self._loading = True

        self.api_status.config(
            text="● Connecting...",
            fg=self.ORANGE
        )

        self.root.update_idletasks()

        if not preserve_page:

            self.current_offset = 0

            self.current_page = 1

        try:

            keyword = (
                self.get_contact_search_keyword()
            )

            data = self.call_get_contacts(
                offset=self.current_offset,
                max_size=self.PAGE_SIZE,
                search=keyword
            )

            contacts, total = (
                self.normalize_response(
                    data
                )
            )

            self.all_contacts = contacts

            self.total_contacts = total

            self.api_status.config(
                text="● Connected",
                fg=self.GREEN
            )

            self.stat_total.value.config(
                text=str(
                    self.total_contacts
                )
            )

            self.populate_contacts(
                contacts
            )

            self.update_pagination()

        except Exception as exc:

            self.api_status.config(
                text="● Disconnected",
                fg=self.RED
            )

            self.stat_total.value.config(
                text="0"
            )

            self.stat_visible.value.config(
                text="0"
            )

            self.clear_tree()

            self.result_label.config(
                text="0 result(s)"
            )

            self.update_pagination()

            self.current_contact = None

            self.current_relation = None

            self.relation_cache = {}

            self.clear_relation_search()

            self.show_contact_details()

            if not preserve_page:

                messagebox.showerror(
                    "Connection Error",
                    "Gagal mengambil data Contact.\n\n"
                    f"{exc}"
                )

        finally:

            self._loading = False

            self.update_restore_button()

    # ========================================================
    # SEARCH KEYWORD
    # ========================================================

    def get_contact_search_keyword(
        self
    ):

        keyword = (
            self.search_var
            .get()
            .strip()
        )

        if not keyword:

            return None

        if (
            keyword.lower()
            == self.search_placeholder.lower()
        ):

            return None

        return keyword

    # ========================================================
    # POPULATE CONTACTS
    # ========================================================

    def populate_contacts(
        self,
        contacts
    ):

        self.clear_tree()

        for contact in contacts:

            if not isinstance(
                contact,
                dict
            ):

                continue

            cid = str(
                contact.get(
                    "id",
                    ""
                )
            ).strip()

            if not cid:

                continue

            if self.tree.exists(
                cid
            ):

                continue

            self.tree.insert(
                "",
                "end",
                iid=cid,
                values=(
                    cid,
                    self.contact_name(
                        contact
                    ),
                    self.val(
                        contact.get(
                            "emailAddress"
                        )
                    ),
                    self.val(
                        contact.get(
                            "phoneNumber"
                        )
                    ),
                    self.val(
                        contact.get(
                            "accountName"
                        )
                    ),
                    self.val(
                        contact.get(
                            "createdAt"
                        )
                    )
                )
            )

        visible = len(
            self.tree.get_children()
        )

        self.result_label.config(
            text=f"{visible} result(s)"
        )

        self.stat_visible.value.config(
            text=str(
                visible
            )
        )

    # ========================================================
    # CLEAR TREE
    # ========================================================

    def clear_tree(
        self
    ):

        for item in (
            self.tree.get_children()
        ):

            self.tree.delete(
                item
            )

    # ========================================================
    # CONTACT SELECT
    # ========================================================

    def on_contact_select(
        self,
        event=None
    ):

        selected = (
            self.tree.selection()
        )

        if not selected:

            return

        cid = selected[0]

        contact = next(
            (
                c
                for c
                in self.all_contacts
                if str(
                    c.get(
                        "id",
                        ""
                    )
                )
                == str(cid)
            ),
            None
        )

        if not contact:

            return

        # ----------------------------------------------------
        # GET FULL CONTACT
        # ----------------------------------------------------

        try:

            getter = getattr(
                api,
                "get_contact",
                None
            )

            if getter:

                detailed = getter(
                    cid
                )

                if isinstance(
                    detailed,
                    dict
                ):

                    contact = detailed

        except Exception:

            # Gunakan data dari list sebagai fallback.
            pass

        self.current_contact = contact

        self.current_relation = None

        self.relation_cache = {}

        self.clear_relation_search()

        self.show_contact_details()

    # ========================================================
    # CONTACT DETAILS
    # ========================================================

    def show_contact_details(
        self
    ):

        if self.current_contact is None:

            selected = (
                self.tree.selection()
            )

            if selected:

                self.on_contact_select()

                return

            self.clear_dynamic()

            self.render_dynamic_title(
                "Contact Details"
            )

            self.render_dynamic_message(
                "Pilih Contact dari tabel."
            )

            self.reset_relation_buttons()

            self.reset_relation_stats()

            self.detail_canvas.yview_moveto(
                0
            )

            return

        self.current_relation = None

        self.clear_dynamic()

        contact = (
            self.current_contact
        )

        name = (
            self.contact_name(
                contact
            )
        )

        self.render_dynamic_title(
            "Contact Details"
        )

        self.profile_card(
            name,
            self.val(
                contact.get(
                    "emailAddress"
                )
            )
        )

        fields = (

            (
                "Nama",
                name
            ),

            (
                "Email",
                contact.get(
                    "emailAddress"
                )
            ),

            (
                "Telepon",
                contact.get(
                    "phoneNumber"
                )
            ),

            (
                "Account",
                contact.get(
                    "accountName"
                )
            ),

            (
                "Created At",
                contact.get(
                    "createdAt"
                )
            ),

            (
                "Created By",
                contact.get(
                    "createdByName"
                )
            ),

            (
                "Modified At",
                contact.get(
                    "modifiedAt"
                )
            ),

            (
                "ID",
                contact.get(
                    "id"
                )
            )
        )

        for label, value in fields:

            self.detail_row(
                label,
                value
            )

        self.set_active_relation_button(
            "contact"
        )

        self.load_relation_counts()

        self.detail_canvas.yview_moveto(
            0
        )

    # ========================================================
    # LOAD RELATIONSHIP
    # ========================================================

    def load_relationship(
        self,
        key
    ):

        if not self.current_contact:

            messagebox.showwarning(
                "Pilih Contact",
                "Pilih Contact terlebih dahulu."
            )

            return

        if key not in self.RELATIONS:

            return

        (
            label,
            entity_name,
            loader_name
        ) = self.RELATIONS[key]

        # ----------------------------------------------------
        # CONTACT
        # ----------------------------------------------------

        if key == "contact":

            self.show_contact_details()

            self.set_active_relation_button(
                "contact"
            )

            return

        # ----------------------------------------------------
        # USE CACHE
        # ----------------------------------------------------

        cached = (
            self.relation_cache.get(
                key
            )
        )

        if cached is not None:

            self.current_relation = key

            self.clear_relation_search()

            self.render_relationship(
                key,
                cached.get(
                    "list",
                    []
                )
            )

            self.set_active_relation_button(
                key
            )

            return

        # ----------------------------------------------------
        # GET API LOADER
        # ----------------------------------------------------

        loader = getattr(
            api,
            loader_name,
            None
        )

        if loader is None:

            messagebox.showerror(
                "API Error",
                f"Fungsi {loader_name}() "
                "tidak ditemukan di api.py."
            )

            return

        try:

            result = (
                self.call_relation_loader(
                    loader,
                    self.current_contact.get(
                        "id"
                    )
                )
            )

            records, total = (
                self.normalize_response(
                    result
                )
            )

            self.relation_cache[key] = {
                "list": records,
                "total": total
            }

            self.current_relation = key

            self.clear_relation_search()

            self.render_relationship(
                key,
                records
            )

            self.set_active_relation_button(
                key
            )

        except Exception as exc:

            messagebox.showerror(
                "Relationship Error",
                f"Gagal mengambil "
                f"{entity_name}.\n\n"
                f"{exc}"
            )

    # ========================================================
    # RENDER RELATIONSHIP
    # ========================================================

    def render_relationship(
        self,
        key,
        records
    ):

        (
            label,
            entity_name,
            _
        ) = self.RELATIONS[key]

        self.clear_dynamic()

        self.render_dynamic_title(
            f"{entity_name} Details"
        )

        contact_name = (
            self.contact_name(
                self.current_contact
            )
        )

        if records:

            first_name = (
                records[0].get(
                    "name",
                    entity_name
                )
            )

        else:

            first_name = (
                f"No {entity_name}"
            )

        self.profile_card(
            first_name,
            f"Related to: {contact_name}"
        )

        if records:

            for index, record in enumerate(
                records,
                start=1
            ):

                self.relationship_card(
                    key,
                    record,
                    index
                )

        else:

            self.render_dynamic_message(
                f"Tidak ada "
                f"{entity_name.lower()} "
                "yang terhubung dengan "
                "Contact ini."
            )

        self.detail_canvas.yview_moveto(
            0
        )

    # ========================================================
    # RELATIONSHIP CARD
    # ========================================================

    def relationship_card(
        self,
        key,
        record,
        index
    ):

        (
            _,
            entity_name,
            _
        ) = self.RELATIONS[key]

        card = tk.Frame(
            self.dynamic_detail,
            bg=self.LIGHT_GRAY,
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        card.pack(
            fill="x",
            padx=18,
            pady=(0, 10)
        )

        tk.Label(
            card,
            text=f"{entity_name.upper()} #{index}",
            bg=self.LIGHT_GRAY,
            fg=self.ACTIVE,
            font=("Segoe UI", 8, "bold")
        ).pack(
            anchor="w",
            padx=12,
            pady=(10, 6)
        )

        # ----------------------------------------------------
        # ACCOUNT
        # ----------------------------------------------------

        if key == "accounts":

            fields = (

                (
                    "Name",
                    record.get(
                        "name"
                    )
                ),

                (
                    "Website",
                    record.get(
                        "website"
                    )
                ),

                (
                    "Industry",
                    record.get(
                        "industry"
                    )
                ),

                (
                    "Type",
                    record.get(
                        "type"
                    )
                ),

                (
                    "Created At",
                    record.get(
                        "createdAt"
                    )
                ),

                (
                    "ID",
                    record.get(
                        "id"
                    )
                )
            )

        # ----------------------------------------------------
        # OPPORTUNITY
        # ----------------------------------------------------

        elif key == "opportunities":

            fields = (

                (
                    "Name",
                    record.get(
                        "name"
                    )
                ),

                (
                    "Stage",
                    record.get(
                        "stage"
                    )
                ),

                (
                    "Amount",
                    record.get(
                        "amount"
                    )
                ),

                (
                    "Currency",
                    record.get(
                        "amountCurrency"
                    )
                ),

                (
                    "Close Date",
                    record.get(
                        "closeDate"
                    )
                ),

                (
                    "Description",
                    record.get(
                        "description"
                    )
                ),

                (
                    "Created At",
                    record.get(
                        "createdAt"
                    )
                ),

                (
                    "ID",
                    record.get(
                        "id"
                    )
                )
            )

        # ----------------------------------------------------
        # CASE
        # ----------------------------------------------------

        else:

            fields = (

                (
                    "Name",
                    record.get(
                        "name"
                    )
                ),

                (
                    "Number",
                    record.get(
                        "number"
                    )
                ),

                (
                    "Status",
                    record.get(
                        "status"
                    )
                ),

                (
                    "Priority",
                    record.get(
                        "priority"
                    )
                ),

                (
                    "Type",
                    record.get(
                        "type"
                    )
                ),

                (
                    "Description",
                    record.get(
                        "description"
                    )
                ),

                (
                    "Created At",
                    record.get(
                        "createdAt"
                    )
                ),

                (
                    "ID",
                    record.get(
                        "id"
                    )
                )
            )

        for label, value in fields:

            self.detail_row(
                label,
                value,
                parent=card,
                padx=12
            )

    # ========================================================
    # RELATIONSHIP COUNTS
    # ========================================================

    def load_relation_counts(
        self
    ):

        if not self.current_contact:

            self.reset_relation_stats()

            return

        cid = (
            self.current_contact.get(
                "id"
            )
        )

        if not cid:

            self.reset_relation_stats()

            return

        try:

            getter = getattr(
                api,
                "get_relationship_summary",
                None
            )

            if getter is None:

                self.reset_relation_stats()

                return

            summary = getter(
                cid
            )

            if not isinstance(
                summary,
                dict
            ):

                self.reset_relation_stats()

                return

            self.stat_accounts.value.config(
                text=str(
                    summary.get(
                        "accounts",
                        0
                    )
                )
            )

            self.stat_opportunities.value.config(
                text=str(
                    summary.get(
                        "opportunities",
                        0
                    )
                )
            )

            self.stat_cases.value.config(
                text=str(
                    summary.get(
                        "cases",
                        0
                    )
                )
            )

        except Exception:

            self.reset_relation_stats()

    # ========================================================
    # RESET RELATION STATS
    # ========================================================

    def reset_relation_stats(
        self
    ):

        self.stat_accounts.value.config(
            text="0"
        )

        self.stat_opportunities.value.config(
            text="0"
        )

        self.stat_cases.value.config(
            text="0"
        )

    # ========================================================
    # ACTIVE RELATIONSHIP BUTTON
    # ========================================================

    def set_active_relation_button(
        self,
        active
    ):

        for key, btn in (
            self.relation_buttons.items()
        ):

            if key == active:

                btn.config(
                    bg=self.ACTIVE,
                    fg=self.WHITE,
                    activebackground=self.BLUE_DARK
                )

            else:

                btn.config(
                    bg=self.WHITE,
                    fg=self.TEXT,
                    activebackground=self.ACTIVE
                )

    # ========================================================
    # RESET RELATION BUTTONS
    # ========================================================

    def reset_relation_buttons(
        self
    ):

        for btn in (
            self.relation_buttons.values()
        ):

            btn.config(
                bg=self.WHITE,
                fg=self.TEXT,
                activebackground=self.ACTIVE
            )

    # ========================================================
    # CLEAR DYNAMIC
    # ========================================================

    def clear_dynamic(
        self
    ):

        for widget in (
            self.dynamic_detail.winfo_children()
        ):

            widget.destroy()

    # ========================================================
    # DYNAMIC TITLE
    # ========================================================

    def render_dynamic_title(
        self,
        text
    ):

        tk.Label(
            self.dynamic_detail,
            text=text,
            bg=self.WHITE,
            fg=self.TEXT,
            font=("Segoe UI", 12, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(8, 12)
        )

    # ========================================================
    # DYNAMIC MESSAGE
    # ========================================================

    def render_dynamic_message(
        self,
        text
    ):

        tk.Label(
            self.dynamic_detail,
            text=text,
            bg=self.WHITE,
            fg=self.MUTED,
            font=("Segoe UI", 9),
            wraplength=300,
            justify="left"
        ).pack(
            anchor="w",
            padx=18,
            pady=15
        )

    # ========================================================
    # PROFILE CARD
    # ========================================================

    def profile_card(
        self,
        name,
        subtitle
    ):

        card = tk.Frame(
            self.dynamic_detail,
            bg=self.LIGHT_GRAY
        )

        card.pack(
            fill="x",
            padx=18,
            pady=(0, 14)
        )

        tk.Label(
            card,
            text=self.initials(
                name
            ),
            bg=self.ACTIVE,
            fg=self.WHITE,
            font=("Segoe UI", 14, "bold"),
            width=3
        ).pack(
            side="left",
            padx=12,
            pady=12
        )

        txt = tk.Frame(
            card,
            bg=self.LIGHT_GRAY
        )

        txt.pack(
            side="left",
            fill="x",
            expand=True,
            pady=10
        )

        tk.Label(
            txt,
            text=name or "-",
            bg=self.LIGHT_GRAY,
            fg=self.TEXT,
            font=("Segoe UI", 10, "bold")
        ).pack(
            anchor="w"
        )

        tk.Label(
            txt,
            text=subtitle or "-",
            bg=self.LIGHT_GRAY,
            fg=self.MUTED,
            font=("Segoe UI", 8)
        ).pack(
            anchor="w",
            pady=(2, 0)
        )

    # ========================================================
    # DETAIL ROW
    # ========================================================

    def detail_row(
        self,
        label,
        value,
        parent=None,
        padx=18
    ):

        parent = (
            parent
            or self.dynamic_detail
        )

        bg = parent.cget(
            "bg"
        )

        row = tk.Frame(
            parent,
            bg=bg
        )

        row.pack(
            fill="x",
            padx=padx,
            pady=4
        )

        tk.Label(
            row,
            text=str(
                label
            ).upper(),
            bg=bg,
            fg="#94A3B8",
            font=("Segoe UI", 8, "bold"),
            width=12,
            anchor="w"
        ).pack(
            side="left",
            anchor="nw"
        )

        tk.Label(
            row,
            text=self.val(
                value
            ),
            bg=bg,
            fg=self.TEXT,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=260
        ).pack(
            side="left",
            fill="x",
            expand=True
        )

    # ========================================================
    # CONTACT SEARCH FOCUS IN
    # ========================================================

    def search_focus_in(
        self,
        event=None
    ):

        if (
            self.search_var.get()
            == self.search_placeholder
        ):

            self.search_entry.delete(
                0,
                "end"
            )

            self.search_entry.config(
                fg=self.TEXT
            )

    # ========================================================
    # CONTACT SEARCH FOCUS OUT
    # ========================================================

    def search_focus_out(
        self,
        event=None
    ):

        if not (
            self.search_var
            .get()
            .strip()
        ):

            self.search_entry.delete(
                0,
                "end"
            )

            self.search_entry.insert(
                0,
                self.search_placeholder
            )

            self.search_entry.config(
                fg="#94A3B8"
            )

    # ========================================================
    # CONTACT SEARCH
    # ========================================================

    def search_contacts(
        self,
        event=None
    ):

        if self.search_after_id:

            try:

                self.root.after_cancel(
                    self.search_after_id
                )

            except Exception:

                pass

        self.search_after_id = (
            self.root.after(
                self.SEARCH_DELAY,
                self.execute_contact_search
            )
        )

    # ========================================================
    # EXECUTE SEARCH
    # ========================================================

    def execute_contact_search(
        self
    ):

        self.search_after_id = None

        keyword = (
            self.get_contact_search_keyword()
        )

        self.current_offset = 0

        self.current_page = 1

        try:

            self.api_status.config(
                text="● Searching...",
                fg=self.ORANGE
            )

            self.root.update_idletasks()

            data = self.call_get_contacts(
                offset=0,
                max_size=self.PAGE_SIZE,
                search=keyword
            )

            contacts, total = (
                self.normalize_response(
                    data
                )
            )

            self.all_contacts = contacts

            self.total_contacts = total

            self.api_status.config(
                text="● Connected",
                fg=self.GREEN
            )

            self.stat_total.value.config(
                text=str(
                    self.total_contacts
                )
            )

            self.populate_contacts(
                contacts
            )

            self.update_pagination()

            self.current_contact = None

            self.current_relation = None

            self.relation_cache = {}

            self.clear_relation_search()

            self.show_contact_details()

        except Exception as exc:

            self.api_status.config(
                text="● Disconnected",
                fg=self.RED
            )

            messagebox.showerror(
                "Search Error",
                f"Gagal mencari Contact.\n\n"
                f"{exc}"
            )

    # ========================================================
    # FOCUS SEARCH
    # ========================================================

    def focus_contact_search(
        self
    ):

        self.search_entry.focus_set()

        if (
            self.search_var.get()
            == self.search_placeholder
        ):

            self.search_entry.delete(
                0,
                "end"
            )

        self.search_entry.select_range(
            0,
            "end"
        )

    # ========================================================
    # PAGINATION
    # ========================================================

    def update_pagination(
        self
    ):

        total_pages = max(
            (
                self.total_contacts
                + self.PAGE_SIZE
                - 1
            )
            // self.PAGE_SIZE,
            1
        )

        if (
            self.current_page
            > total_pages
        ):

            self.current_page = (
                total_pages
            )

            self.current_offset = (
                (
                    total_pages
                    - 1
                )
                * self.PAGE_SIZE
            )

        self.page_label.config(
            text=(
                f"Page "
                f"{self.current_page}"
                f" / "
                f"{total_pages}"
            )
        )

        if (
            self.current_page
            <= 1
        ):

            self.previous_button.state(
                ["disabled"]
            )

        else:

            self.previous_button.state(
                ["!disabled"]
            )

        if (
            self.current_page
            >= total_pages
        ):

            self.next_button.state(
                ["disabled"]
            )

        else:

            self.next_button.state(
                ["!disabled"]
            )

    # ========================================================
    # NEXT PAGE
    # ========================================================

    def next_page(
        self
    ):

        if (
            self.current_offset
            + self.PAGE_SIZE
            >= self.total_contacts
        ):

            return

        self.current_offset += (
            self.PAGE_SIZE
        )

        self.current_page += 1

        self.load_data(
            preserve_page=True
        )

    # ========================================================
    # PREVIOUS PAGE
    # ========================================================

    def previous_page(
        self
    ):

        if (
            self.current_offset
            <= 0
        ):

            return

        self.current_offset = max(
            self.current_offset
            - self.PAGE_SIZE,
            0
        )

        self.current_page = max(
            self.current_page
            - 1,
            1
        )

        self.load_data(
            preserve_page=True
        )

    # ========================================================
    # RELATION SEARCH FOCUS IN
    # ========================================================

    def relation_search_focus_in(
        self,
        event=None
    ):

        if (
            self.relation_search_var.get()
            == self.relation_search_placeholder
        ):

            self.relation_search_entry.delete(
                0,
                "end"
            )

            self.relation_search_entry.config(
                fg=self.TEXT
            )

    # ========================================================
    # RELATION SEARCH FOCUS OUT
    # ========================================================

    def relation_search_focus_out(
        self,
        event=None
    ):

        if not (
            self.relation_search_var
            .get()
            .strip()
        ):

            self.relation_search_entry.delete(
                0,
                "end"
            )

            self.relation_search_entry.insert(
                0,
                self.relation_search_placeholder
            )

            self.relation_search_entry.config(
                fg="#94A3B8"
            )

    # ========================================================
    # CLEAR RELATION SEARCH
    # ========================================================

    def clear_relation_search(
        self
    ):

        if not hasattr(
            self,
            "relation_search_var"
        ):

            return

        if self.relation_search_after_id:

            try:

                self.root.after_cancel(
                    self.relation_search_after_id
                )

            except Exception:

                pass

            self.relation_search_after_id = None

        self.relation_search_var.set(
            self.relation_search_placeholder
        )

        self.relation_search_entry.config(
            fg="#94A3B8"
        )

    # ========================================================
    # FILTER RELATIONSHIP
    # ========================================================

    def filter_relationship(
        self,
        event=None
    ):

        if not self.current_relation:

            return

        if self.relation_search_after_id:

            try:

                self.root.after_cancel(
                    self.relation_search_after_id
                )

            except Exception:

                pass

        self.relation_search_after_id = (
            self.root.after(
                self.RELATION_SEARCH_DELAY,
                self.execute_relationship_filter
            )
        )

    # ========================================================
    # EXECUTE RELATIONSHIP FILTER
    # ========================================================

    def execute_relationship_filter(
        self
    ):

        self.relation_search_after_id = None

        if not self.current_relation:

            return

        keyword = (
            self.relation_search_var
            .get()
            .strip()
            .lower()
        )

        if (
            keyword
            == self.relation_search_placeholder.lower()
        ):

            keyword = ""

        cached = (
            self.relation_cache.get(
                self.current_relation,
                {}
            )
        )

        records = cached.get(
            "list",
            []
        )

        if keyword:

            filtered = []

            for record in records:

                searchable = " ".join(
                    [
                        str(
                            record.get(
                                "id",
                                ""
                            )
                        ),

                        str(
                            record.get(
                                "name",
                                ""
                            )
                        ),

                        self.relationship_info(
                            self.current_relation,
                            record
                        )
                    ]
                ).lower()

                if keyword in searchable:

                    filtered.append(
                        record
                    )

            records = filtered

        self.render_relationship(
            self.current_relation,
            records
        )

        self.set_active_relation_button(
            self.current_relation
        )

    # ========================================================
    # ADD CONTACT
    # ========================================================

    def action_add(
        self
    ):

        if ContactForm is None:

            messagebox.showinfo(
                "Add Contact",
                "contact_form.py belum tersedia."
            )

            return

        try:

            ContactForm(
                self.root,
                on_success=(
                    self.after_contact_form_success
                )
            )

        except TypeError:

            try:

                ContactForm(
                    self.root
                )

            except Exception as exc:

                messagebox.showerror(
                    "Add Contact Error",
                    str(exc)
                )

    # ========================================================
    # EDIT CONTACT
    # ========================================================

    def action_edit(
        self
    ):

        selected = (
            self.tree.selection()
        )

        if not selected:

            messagebox.showwarning(
                "Edit Contact",
                "Pilih Contact terlebih dahulu."
            )

            return

        if ContactForm is None:

            messagebox.showinfo(
                "Edit Contact",
                "contact_form.py belum tersedia."
            )

            return

        cid = selected[0]

        try:

            getter = getattr(
                api,
                "get_contact",
                None
            )

            if getter is None:

                raise AttributeError(
                    "Fungsi get_contact() "
                    "tidak ditemukan di api.py."
                )

            contact = getter(
                cid
            )

            try:

                ContactForm(
                    self.root,
                    contact=contact,
                    on_success=(
                        self.after_contact_form_success
                    )
                )

            except TypeError:

                ContactForm(
                    self.root,
                    contact=contact
                )

        except Exception as exc:

            messagebox.showerror(
                "Edit Error",
                str(exc)
            )

    # ========================================================
    # CONTACT FORM CALLBACK
    # ========================================================

    def after_contact_form_success(
        self,
        *args,
        **kwargs
    ):

        self.current_contact = None

        self.current_relation = None

        self.relation_cache = {}

        self.load_data()

    # ========================================================
    # DELETE CONTACT
    # ========================================================

    def action_delete(
        self
    ):

        selected = (
            self.tree.selection()
        )

        if not selected:

            messagebox.showwarning(
                "Delete Contact",
                "Pilih Contact terlebih dahulu."
            )

            return

        cid = selected[0]

        # ----------------------------------------------------
        # GET CONTACT SNAPSHOT
        # ----------------------------------------------------

        try:

            getter = getattr(
                api,
                "get_contact",
                None
            )

            if getter:

                contact = getter(
                    cid
                )

            else:

                contact = next(
                    (
                        c
                        for c
                        in self.all_contacts
                        if str(
                            c.get(
                                "id",
                                ""
                            )
                        )
                        == str(cid)
                    ),
                    {}
                )

        except Exception:

            contact = next(
                (
                    c
                    for c
                    in self.all_contacts
                    if str(
                        c.get(
                            "id",
                            ""
                        )
                    )
                    == str(cid)
                ),
                {}
            )

        name = (
            self.contact_name(
                contact
            )
        )

        confirmed = messagebox.askyesno(
            "Delete Contact",
            "Yakin ingin menghapus:\n\n"
            f"{name}?\n\n"
            "Contact dapat dipulihkan dengan "
            "Ctrl + Z setelah berhasil dihapus."
        )

        if not confirmed:

            return

        try:

            deleter = getattr(
                api,
                "delete_contact",
                None
            )

            if deleter is None:

                raise AttributeError(
                    "Fungsi delete_contact() "
                    "tidak ditemukan di api.py."
                )

            deleter(
                cid
            )

            # ------------------------------------------------
            # SAVE UNDO SNAPSHOT
            # ------------------------------------------------

            if contact:

                self.deleted_contacts.append(
                    contact.copy()
                )

            # ------------------------------------------------
            # RESET STATE
            # ------------------------------------------------

            self.current_contact = None

            self.current_relation = None

            self.relation_cache = {}

            self.load_data()

            self.update_restore_button()

            messagebox.showinfo(
                "Berhasil",
                "Contact berhasil dihapus.\n\n"
                "Tekan Ctrl + Z atau klik "
                "↶ Restore untuk memulihkannya."
            )

        except Exception as exc:

            messagebox.showerror(
                "Delete Error",
                str(exc)
            )

    # ========================================================
    # RESTORE CONTACT
    # ========================================================

    def action_restore(
        self,
        event=None
    ):

        if not self.deleted_contacts:

            messagebox.showinfo(
                "Restore Contact",
                "Tidak ada Contact yang dapat "
                "dipulihkan."
            )

            return "break"

        # ----------------------------------------------------
        # LAST DELETED CONTACT
        # ----------------------------------------------------

        contact = (
            self.deleted_contacts[-1]
        )

        name = (
            self.contact_name(
                contact
            )
        )

        email = (
            self.val(
                contact.get(
                    "emailAddress"
                )
            )
        )

        confirmed = messagebox.askyesno(
            "Restore Contact",
            "Pulihkan kembali Contact berikut?\n\n"
            f"{name}\n"
            f"{email}\n\n"
            "Data akan dibuat kembali di EspoCRM."
        )

        if not confirmed:

            return "break"

        try:

            restored = (
                self.create_contact_from_snapshot(
                    contact
                )
            )

            # Hapus dari stack hanya jika CREATE berhasil.
            self.deleted_contacts.pop()

            self.current_contact = None

            self.current_relation = None

            self.relation_cache = {}

            self.load_data()

            self.update_restore_button()

            restored_id = ""

            if isinstance(
                restored,
                dict
            ):

                restored_id = (
                    restored.get(
                        "id",
                        ""
                    )
                )

            self.select_restored_contact(
                contact,
                restored_id
            )

            if restored_id:

                messagebox.showinfo(
                    "Restore Berhasil",
                    "Contact berhasil dipulihkan.\n\n"
                    f"Nama: {name}\n"
                    f"ID baru: {restored_id}"
                )

            else:

                messagebox.showinfo(
                    "Restore Berhasil",
                    "Contact berhasil dipulihkan."
                )

        except Exception as exc:

            messagebox.showerror(
                "Restore Error",
                "Contact gagal dipulihkan.\n\n"
                f"{exc}"
            )

        return "break"

    # ========================================================
    # CREATE CONTACT FROM SNAPSHOT
    # ========================================================

    def create_contact_from_snapshot(
        self,
        contact
    ):

        creator = getattr(
            api,
            "create_contact",
            None
        )

        if creator is None:

            raise AttributeError(
                "Fungsi create_contact() "
                "tidak ditemukan di api.py."
            )

        payload = {}

        # ----------------------------------------------------
        # BASIC FIELDS
        # ----------------------------------------------------

        fields = (
            "firstName",
            "lastName",
            "emailAddress",
            "phoneNumber",
            "accountId"
        )

        for field in fields:

            value = contact.get(
                field
            )

            if (
                value is not None
                and value != ""
            ):

                payload[field] = value

        # ----------------------------------------------------
        # FALLBACK NAME
        # ----------------------------------------------------

        if (
            not payload.get(
                "firstName"
            )
            and not payload.get(
                "lastName"
            )
            and contact.get(
                "name"
            )
        ):

            name_parts = (
                str(
                    contact.get(
                        "name"
                    )
                )
                .strip()
                .split()
            )

            if len(
                name_parts
            ) >= 2:

                payload["firstName"] = (
                    " ".join(
                        name_parts[:-1]
                    )
                )

                payload["lastName"] = (
                    name_parts[-1]
                )

            elif name_parts:

                payload["firstName"] = (
                    name_parts[0]
                )

        # ----------------------------------------------------
        # PRIMARY METHOD
        # ----------------------------------------------------

        try:

            return creator(
                payload
            )

        except TypeError as first_error:

            pass

        # ----------------------------------------------------
        # FALLBACK SIGNATURE
        # ----------------------------------------------------

        try:

            signature = inspect.signature(
                creator
            )

        except (
            TypeError,
            ValueError
        ):

            raise first_error

        aliases = {

            "firstname":
                payload.get(
                    "firstName"
                ),

            "first":
                payload.get(
                    "firstName"
                ),

            "lastname":
                payload.get(
                    "lastName"
                ),

            "last":
                payload.get(
                    "lastName"
                ),

            "email":
                payload.get(
                    "emailAddress"
                ),

            "emailaddress":
                payload.get(
                    "emailAddress"
                ),

            "phone":
                payload.get(
                    "phoneNumber"
                ),

            "phonenumber":
                payload.get(
                    "phoneNumber"
                ),

            "accountid":
                payload.get(
                    "accountId"
                ),

            "account":
                payload.get(
                    "accountId"
                ),

            "data":
                payload,

            "payload":
                payload,

            "contact":
                payload
        }

        kwargs = {}

        for param_name, parameter in (
            signature.parameters.items()
        ):

            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD
            ):

                continue

            normalized = (
                param_name
                .replace(
                    "_",
                    ""
                )
                .lower()
            )

            if normalized in aliases:

                value = aliases[
                    normalized
                ]

                if value is not None:

                    kwargs[
                        param_name
                    ] = value

        return creator(
            **kwargs
        )

    # ========================================================
    # SELECT RESTORED CONTACT
    # ========================================================

    def select_restored_contact(
        self,
        original_contact,
        restored_id=None
    ):

        # ----------------------------------------------------
        # 1. ID
        # ----------------------------------------------------

        if restored_id:

            restored_id = str(
                restored_id
            )

            if self.tree.exists(
                restored_id
            ):

                self.tree.selection_set(
                    restored_id
                )

                self.tree.focus(
                    restored_id
                )

                self.tree.see(
                    restored_id
                )

                return

        # ----------------------------------------------------
        # 2. EMAIL
        # ----------------------------------------------------

        original_email = (
            str(
                original_contact.get(
                    "emailAddress",
                    ""
                )
            )
            .strip()
            .lower()
        )

        if original_email:

            for contact in (
                self.all_contacts
            ):

                email = (
                    str(
                        contact.get(
                            "emailAddress",
                            ""
                        )
                    )
                    .strip()
                    .lower()
                )

                if email == original_email:

                    self.select_contact_data(
                        contact
                    )

                    return

        # ----------------------------------------------------
        # 3. NAME
        # ----------------------------------------------------

        original_name = (
            self.contact_name(
                original_contact
            )
            .strip()
            .lower()
        )

        if original_name:

            for contact in (
                self.all_contacts
            ):

                current_name = (
                    self.contact_name(
                        contact
                    )
                    .strip()
                    .lower()
                )

                if current_name == original_name:

                    self.select_contact_data(
                        contact
                    )

                    return

    # ========================================================
    # SELECT CONTACT DATA
    # ========================================================

    def select_contact_data(
        self,
        contact
    ):

        cid = str(
            contact.get(
                "id",
                ""
            )
        )

        if (
            cid
            and self.tree.exists(
                cid
            )
        ):

            self.tree.selection_set(
                cid
            )

            self.tree.focus(
                cid
            )

            self.tree.see(
                cid
            )

    # ========================================================
    # RESTORE BUTTON
    # ========================================================

    def update_restore_button(
        self
    ):

        if not hasattr(
            self,
            "restore_button"
        ):

            return

        count = len(
            self.deleted_contacts
        )

        if count:

            self.restore_button.state(
                ["!disabled"]
            )

            self.restore_button.config(
                text=f"↶ Restore ({count})"
            )

        else:

            self.restore_button.state(
                ["disabled"]
            )

            self.restore_button.config(
                text="↶ Restore"
            )

    # ========================================================
    # EXPORT CSV
    # ========================================================

    def action_export(
        self
    ):

        rows = (
            self.tree.get_children()
        )

        if not rows:

            messagebox.showwarning(
                "Export CSV",
                "Tidak ada data untuk diekspor."
            )

            return

        path = filedialog.asksaveasfilename(
            title="Export Contacts",
            defaultextension=".csv",
            filetypes=[
                (
                    "CSV Files",
                    "*.csv"
                )
            ]
        )

        if not path:

            return

        try:

            with open(
                path,
                "w",
                newline="",
                encoding="utf-8-sig"
            ) as file:

                writer = csv.writer(
                    file
                )

                columns = (
                    self.tree["columns"]
                )

                writer.writerow(
                    [
                        self.tree.heading(
                            column
                        )["text"]
                        for column in columns
                    ]
                )

                for row in rows:

                    writer.writerow(
                        self.tree.item(
                            row
                        )["values"]
                    )

            messagebox.showinfo(
                "Export Berhasil",
                "Data berhasil diekspor ke:\n"
                f"{path}"
            )

        except Exception as exc:

            messagebox.showerror(
                "Export Error",
                str(exc)
            )

    # ========================================================
    # EXIT
    # ========================================================

    def action_exit(
        self
    ):

        if self._closing:

            return

        confirmed = messagebox.askyesno(
            "Konfirmasi Keluar",
            "Apakah Anda yakin ingin keluar?"
        )

        if not confirmed:

            return

        self._closing = True

        # ----------------------------------------------------
        # CANCEL SEARCH TIMER
        # ----------------------------------------------------

        if self.search_after_id:

            try:

                self.root.after_cancel(
                    self.search_after_id
                )

            except Exception:

                pass

        # ----------------------------------------------------
        # CANCEL RELATION SEARCH TIMER
        # ----------------------------------------------------

        if self.relation_search_after_id:

            try:

                self.root.after_cancel(
                    self.relation_search_after_id
                )

            except Exception:

                pass

        self.root.destroy()

    # ========================================================
    # VALUE FORMATTER
    # ========================================================

    @staticmethod
    def val(
        value
    ):

        if value is None:

            return "-"

        if (
            isinstance(
                value,
                str
            )
            and not value.strip()
        ):

            return "-"

        return str(
            value
        )

    # ========================================================
    # CONTACT NAME
    # ========================================================

    @staticmethod
    def contact_name(
        contact
    ):

        if not isinstance(
            contact,
            dict
        ):

            return "-"

        name = contact.get(
            "name"
        )

        if name:

            return str(
                name
            )

        name = (
            f"{contact.get('firstName', '')} "
            f"{contact.get('lastName', '')}"
        ).strip()

        return name or "-"

    # ========================================================
    # INITIALS
    # ========================================================

    @staticmethod
    def initials(
        name
    ):

        parts = (
            str(
                name or "?"
            )
            .strip()
            .split()
        )

        if not parts:

            return "?"

        if len(parts) == 1:

            return (
                parts[0][:2]
                .upper()
            )

        return (
            parts[0][0]
            + parts[-1][0]
        ).upper()

    # ========================================================
    # RELATIONSHIP INFO
    # ========================================================

    def relationship_info(
        self,
        key,
        record
    ):

        if key == "accounts":

            return self.first(
                record.get(
                    "website"
                ),
                record.get(
                    "industry"
                ),
                record.get(
                    "type"
                ),
                "-"
            )

        if key == "opportunities":

            return self.first(
                record.get(
                    "stage"
                ),
                record.get(
                    "closeDate"
                ),
                record.get(
                    "amount"
                ),
                "-"
            )

        if key == "cases":

            return self.first(
                record.get(
                    "status"
                ),
                record.get(
                    "priority"
                ),
                record.get(
                    "number"
                ),
                "-"
            )

        return "-"

    # ========================================================
    # FIRST NON EMPTY VALUE
    # ========================================================

    @staticmethod
    def first(
        *values
    ):

        for value in values:

            if (
                value is not None
                and str(
                    value
                ).strip()
            ):

                return str(
                    value
                )

        return "-"


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    Dashboard()