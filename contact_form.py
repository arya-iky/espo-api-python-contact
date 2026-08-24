"""
contact_form.py
============================================================

Form Tkinter untuk menambah dan mengedit Contact pada EspoCRM.

FITUR
------------------------------------------------------------
- Tambah Contact
- Edit Contact
- Tombol "Konfirmasi Edit" khusus mode edit
- Data Edit otomatis terisi
- Validasi First Name
- Validasi Last Name
- Validasi Email
- Validasi Nomor Telepon
- Integrasi langsung dengan api.py
- Callback ke Dashboard
- Callback Undo / Redo melalui on_change
- Kompatibel dengan:
      ContactForm(..., contact_data={})
  maupun:
      ContactForm(..., contact={})
- Callback lama tanpa argument tetap didukung
- Ctrl + S untuk menyimpan
- Escape untuk menutup
- Mencegah double submit
- Error API ditampilkan dengan jelas
- UI menggunakan tk.Button agar stabil
"""

import re
import inspect
import tkinter as tk
from tkinter import messagebox

import api


class ContactForm:

    # ============================================================
    # COLORS
    # ============================================================

    BG = "#F4F6F9"
    CARD = "#FFFFFF"

    PRIMARY = "#2563EB"
    PRIMARY_HOVER = "#1D4ED8"

    SECONDARY = "#E2E8F0"
    SECONDARY_HOVER = "#CBD5E1"

    TEXT = "#172033"
    MUTED = "#64748B"

    BORDER = "#D9E1EC"

    RED = "#DC2626"
    RED_LIGHT = "#FEF2F2"

    GREEN = "#10B981"
    GREEN_HOVER = "#059669"

    # ============================================================
    # WINDOW
    # ============================================================

    WINDOW_WIDTH = 620
    WINDOW_HEIGHT = 700

    # ============================================================
    # INIT
    # ============================================================

    def __init__(
        self,
        parent,
        on_success=None,
        contact_data=None,
        contact=None,
        on_change=None
    ):
        """
        Parameters
        ----------
        parent:
            Parent window Dashboard.

        on_success:
            Callback setelah create/update berhasil.

            Mendukung:

                on_success(updated_contact)

            maupun callback lama:

                on_success()

        contact_data:
            Dictionary Contact untuk mode Edit.

        contact:
            Alias dari contact_data.

        on_change:
            Callback untuk Undo / Redo.

            Format:

                on_change(
                    action,
                    old_data,
                    new_data
                )

            Action:

                "create"
                "update"
        """

        self.parent = parent

        self.on_success = on_success
        self.on_change = on_change

        self.is_saving = False
        self.is_closed = False
        self.is_success = False

        self.validation_labels = {}

        # ========================================================
        # CONTACT DATA COMPATIBILITY
        # ========================================================

        if contact_data is not None:
            selected_contact = contact_data
        else:
            selected_contact = contact

        if (
            selected_contact is not None
            and not isinstance(selected_contact, dict)
        ):
            raise ValueError(
                "Data Contact harus berupa dictionary."
            )

        if isinstance(selected_contact, dict):
            self.contact = dict(selected_contact)
        else:
            self.contact = None

        # ========================================================
        # MODE
        # ========================================================

        self.is_edit = (
            self.contact is not None
            and bool(self.contact.get("id"))
        )

        # ========================================================
        # WINDOW
        # ========================================================

        self.window = tk.Toplevel(parent)

        if self.is_edit:
            self.window.title(
                "Edit Contact - EspoCRM"
            )
        else:
            self.window.title(
                "Tambah Contact - EspoCRM"
            )

        self.window.geometry(
            f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}"
        )

        self.window.minsize(
            self.WINDOW_WIDTH,
            self.WINDOW_HEIGHT
        )

        self.window.resizable(
            False,
            False
        )

        self.window.configure(
            bg=self.BG
        )

        self.window.transient(parent)

        # ========================================================
        # MODAL
        # ========================================================

        try:
            self.window.grab_set()
        except tk.TclError:
            pass

        self.window.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

        # ========================================================
        # BUILD UI
        # ========================================================

        self.build_ui()

        # ========================================================
        # LOAD CONTACT
        # ========================================================

        if self.is_edit:
            self.load_contact_data()

        # ========================================================
        # KEYBOARD
        # ========================================================

        self.window.bind(
            "<Escape>",
            self.handle_escape
        )

        self.window.bind(
            "<Control-s>",
            self.handle_save_shortcut
        )

        # ========================================================
        # CENTER
        # ========================================================

        self.center_window()

        # ========================================================
        # FOCUS
        # ========================================================

        try:
            self.first_name_entry.focus_set()
        except tk.TclError:
            pass

    # ============================================================
    # CENTER WINDOW
    # ============================================================

    def center_window(self):
        """Menempatkan window di tengah layar."""

        self.window.update_idletasks()

        width = self.WINDOW_WIDTH
        height = self.WINDOW_HEIGHT

        screen_width = (
            self.window.winfo_screenwidth()
        )

        screen_height = (
            self.window.winfo_screenheight()
        )

        x = (
            screen_width - width
        ) // 2

        y = (
            screen_height - height
        ) // 2

        if x < 0:
            x = 0

        if y < 0:
            y = 0

        self.window.geometry(
            f"{width}x{height}+{x}+{y}"
        )

    # ============================================================
    # BUILD UI
    # ============================================================

    def build_ui(self):

        main = tk.Frame(
            self.window,
            bg=self.BG
        )

        main.pack(
            fill="both",
            expand=True,
            padx=24,
            pady=24
        )

        # --------------------------------------------------------
        # HEADER
        # --------------------------------------------------------

        self.build_header(main)

        # --------------------------------------------------------
        # FORM CARD
        # --------------------------------------------------------

        form_card = tk.Frame(
            main,
            bg=self.CARD,
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        form_card.pack(
            fill="both",
            expand=True,
            pady=(14, 0)
        )

        # --------------------------------------------------------
        # FORM
        # --------------------------------------------------------

        form = tk.Frame(
            form_card,
            bg=self.CARD
        )

        form.pack(
            fill="x",
            padx=28,
            pady=(24, 8)
        )

        form.columnconfigure(
            1,
            weight=1
        )

        # --------------------------------------------------------
        # FIRST NAME
        # --------------------------------------------------------

        self.create_field(
            parent=form,
            row=0,
            label="First Name",
            required=True,
            entry_name="first_name_entry"
        )

        # --------------------------------------------------------
        # LAST NAME
        # --------------------------------------------------------

        self.create_field(
            parent=form,
            row=1,
            label="Last Name",
            required=True,
            entry_name="last_name_entry"
        )

        # --------------------------------------------------------
        # EMAIL
        # --------------------------------------------------------

        self.create_field(
            parent=form,
            row=2,
            label="Email",
            required=True,
            entry_name="email_entry"
        )

        # --------------------------------------------------------
        # PHONE
        # --------------------------------------------------------

        self.create_field(
            parent=form,
            row=3,
            label="Phone",
            required=True,
            entry_name="phone_entry"
        )

        # --------------------------------------------------------
        # ACCOUNT INFO
        # --------------------------------------------------------

        account_value = self.get_account_display()

        self.account_label = tk.Label(
            form,
            text=(
                f"Account terkait: {account_value}"
            ),
            bg=self.CARD,
            fg=self.MUTED,
            font=(
                "Segoe UI",
                9
            ),
            anchor="w"
        )

        self.account_label.grid(
            row=4,
            column=1,
            sticky="w",
            pady=(5, 8)
        )

        # --------------------------------------------------------
        # INFO PANEL
        # --------------------------------------------------------

        info = tk.Frame(
            form_card,
            bg="#F8FAFC",
            highlightbackground="#E2E8F0",
            highlightthickness=1
        )

        info.pack(
            fill="x",
            padx=28,
            pady=(6, 12)
        )

        if self.is_edit:

            info_text = (
                "Edit mode aktif. Data Contact yang dipilih "
                "telah dimuat. Silakan ubah informasi yang "
                "diperlukan, kemudian tekan Konfirmasi Edit."
            )

        else:

            info_text = (
                "Tambah Contact baru. Semua field bertanda "
                "'*' wajib diisi."
            )

        tk.Label(
            info,
            text="ⓘ",
            bg="#F8FAFC",
            fg=self.PRIMARY,
            font=(
                "Segoe UI",
                12,
                "bold"
            )
        ).pack(
            side="left",
            padx=(12, 7),
            pady=10
        )

        tk.Label(
            info,
            text=info_text,
            bg="#F8FAFC",
            fg=self.MUTED,
            font=(
                "Segoe UI",
                9
            ),
            anchor="w",
            justify="left",
            wraplength=500
        ).pack(
            side="left",
            fill="x",
            expand=True,
            pady=10
        )

        # --------------------------------------------------------
        # BUTTON AREA
        # --------------------------------------------------------

        button_area = tk.Frame(
            form_card,
            bg=self.CARD
        )

        button_area.pack(
            fill="x",
            padx=28,
            pady=(4, 20)
        )

        # --------------------------------------------------------
        # CANCEL
        # --------------------------------------------------------

        self.cancel_button = tk.Button(
            button_area,

            text="Batal",

            command=self.close,

            relief="flat",
            bd=0,

            bg=self.SECONDARY,
            fg=self.TEXT,

            activebackground=self.SECONDARY_HOVER,
            activeforeground=self.TEXT,

            disabledforeground="#94A3B8",

            font=(
                "Segoe UI",
                10,
                "bold"
            ),

            padx=18,
            pady=9,

            cursor="hand2"
        )

        self.cancel_button.pack(
            side="right"
        )

        # --------------------------------------------------------
        # SAVE
        # --------------------------------------------------------

        if self.is_edit:

            save_text = (
                "✓  Konfirmasi Edit"
            )

        else:

            save_text = (
                "+  Simpan Contact"
            )

        self.save_button = tk.Button(
            button_area,

            text=save_text,

            command=self.save_contact,

            relief="flat",
            bd=0,

            bg=self.PRIMARY,
            fg="#FFFFFF",

            activebackground=self.PRIMARY_HOVER,
            activeforeground="#FFFFFF",

            disabledforeground="#CBD5E1",

            font=(
                "Segoe UI",
                10,
                "bold"
            ),

            padx=18,
            pady=9,

            cursor="hand2"
        )

        self.save_button.pack(
            side="right",
            padx=(0, 10)
        )

        # --------------------------------------------------------
        # HOVER
        # --------------------------------------------------------

        self.bind_button_hover(
            self.save_button,
            self.PRIMARY,
            self.PRIMARY_HOVER
        )

        self.bind_button_hover(
            self.cancel_button,
            self.SECONDARY,
            self.SECONDARY_HOVER
        )

    # ============================================================
    # HEADER
    # ============================================================

    def build_header(self, parent):

        header = tk.Frame(
            parent,
            bg=self.CARD,
            highlightbackground=self.BORDER,
            highlightthickness=1
        )

        header.pack(
            fill="x"
        )

        inner = tk.Frame(
            header,
            bg=self.CARD
        )

        inner.pack(
            fill="x",
            padx=22,
            pady=18
        )

        # --------------------------------------------------------
        # ICON
        # --------------------------------------------------------

        icon_text = (
            "✎"
            if self.is_edit
            else "+"
        )

        icon = tk.Label(
            inner,
            text=icon_text,
            bg=self.PRIMARY,
            fg="#FFFFFF",
            font=(
                "Segoe UI",
                21,
                "bold"
            ),
            width=2,
            height=1
        )

        icon.pack(
            side="left",
            padx=(0, 14)
        )

        # --------------------------------------------------------
        # TEXT
        # --------------------------------------------------------

        text_frame = tk.Frame(
            inner,
            bg=self.CARD
        )

        text_frame.pack(
            side="left",
            fill="x",
            expand=True
        )

        if self.is_edit:

            title = "Edit Contact"

            subtitle = (
                "Perbarui informasi Contact "
                "yang dipilih."
            )

        else:

            title = "Tambah Contact"

            subtitle = (
                "Masukkan informasi Contact "
                "baru ke EspoCRM."
            )

        tk.Label(
            text_frame,
            text=title,
            bg=self.CARD,
            fg=self.TEXT,
            font=(
                "Segoe UI",
                17,
                "bold"
            ),
            anchor="w"
        ).pack(
            anchor="w"
        )

        tk.Label(
            text_frame,
            text=subtitle,
            bg=self.CARD,
            fg=self.MUTED,
            font=(
                "Segoe UI",
                9
            ),
            anchor="w"
        ).pack(
            anchor="w",
            pady=(2, 0)
        )

    # ============================================================
    # CREATE FIELD
    # ============================================================

    def create_field(
        self,
        parent,
        row,
        label,
        required,
        entry_name
    ):

        label_text = label

        if required:
            label_text += " *"

        label_widget = tk.Label(
            parent,
            text=label_text,
            bg=self.CARD,
            fg=self.TEXT,
            font=(
                "Segoe UI",
                10,
                "bold"
            ),
            anchor="w"
        )

        label_widget.grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 18),
            pady=7
        )

        # --------------------------------------------------------
        # ENTRY FRAME
        # --------------------------------------------------------

        entry_frame = tk.Frame(
            parent,
            bg=self.CARD
        )

        entry_frame.grid(
            row=row,
            column=1,
            sticky="ew",
            pady=4
        )

        entry_frame.columnconfigure(
            0,
            weight=1
        )

        # --------------------------------------------------------
        # ENTRY
        # --------------------------------------------------------

        entry = tk.Entry(
            entry_frame,

            bg="#FFFFFF",
            fg=self.TEXT,
            insertbackground=self.TEXT,

            relief="solid",
            bd=1,

            highlightthickness=1,
            highlightbackground=self.BORDER,
            highlightcolor=self.PRIMARY,

            font=(
                "Segoe UI",
                10
            )
        )

        entry.grid(
            row=0,
            column=0,
            sticky="ew",
            ipady=7
        )

        setattr(
            self,
            entry_name,
            entry
        )

        # --------------------------------------------------------
        # VALIDATION LABEL
        # --------------------------------------------------------

        error_label = tk.Label(
            entry_frame,
            text="",
            bg=self.CARD,
            fg=self.RED,
            font=(
                "Segoe UI",
                8
            ),
            anchor="w"
        )

        error_label.grid(
            row=1,
            column=0,
            sticky="w"
        )

        self.validation_labels[
            entry_name
        ] = error_label

    # ============================================================
    # BUTTON HOVER
    # ============================================================

    def bind_button_hover(
        self,
        button,
        normal,
        hover
    ):

        def on_enter(event):

            try:

                if button["state"] != "disabled":

                    button.configure(
                        bg=hover
                    )

            except tk.TclError:

                pass

        def on_leave(event):

            try:

                if button["state"] != "disabled":

                    button.configure(
                        bg=normal
                    )

            except tk.TclError:

                pass

        button.bind(
            "<Enter>",
            on_enter
        )

        button.bind(
            "<Leave>",
            on_leave
        )

    # ============================================================
    # GET ACCOUNT DISPLAY
    # ============================================================

    def get_account_display(self):

        if not self.contact:

            return "-"

        account_value = (
            self.contact.get(
                "accountName"
            )
        )

        if not account_value:

            account_value = (
                self.contact.get(
                    "account"
                )
            )

        if isinstance(
            account_value,
            dict
        ):

            account_value = (
                account_value.get(
                    "name"
                )
                or "-"
            )

        return self.val(
            account_value
        )

    # ============================================================
    # LOAD CONTACT DATA
    # ============================================================

    def load_contact_data(self):

        if not isinstance(
            self.contact,
            dict
        ):
            return

        self.set_entry_value(
            self.first_name_entry,
            self.contact.get(
                "firstName",
                ""
            )
        )

        self.set_entry_value(
            self.last_name_entry,
            self.contact.get(
                "lastName",
                ""
            )
        )

        self.set_entry_value(
            self.email_entry,
            self.contact.get(
                "emailAddress",
                ""
            )
        )

        self.set_entry_value(
            self.phone_entry,
            self.contact.get(
                "phoneNumber",
                ""
            )
        )

    # ============================================================
    # SET ENTRY VALUE
    # ============================================================

    @staticmethod
    def set_entry_value(
        entry,
        value
    ):

        entry.delete(
            0,
            "end"
        )

        if value is None:
            return

        entry.insert(
            0,
            str(value)
        )

    # ============================================================
    # GET FORM DATA
    # ============================================================

    def get_form_data(self):

        return {
            "firstName": (
                self.first_name_entry
                .get()
                .strip()
            ),

            "lastName": (
                self.last_name_entry
                .get()
                .strip()
            ),

            "emailAddress": (
                self.email_entry
                .get()
                .strip()
            ),

            "phoneNumber": (
                self.phone_entry
                .get()
                .strip()
            )
        }

    # ============================================================
    # CLEAR VALIDATION
    # ============================================================

    def clear_validation(self):

        for label in self.validation_labels.values():

            label.config(
                text=""
            )

    # ============================================================
    # SET VALIDATION
    # ============================================================

    def set_validation(
        self,
        entry_name,
        message
    ):

        label = self.validation_labels.get(
            entry_name
        )

        if label:

            label.config(
                text=message
            )

    # ============================================================
    # VALIDATE NAME
    # ============================================================

    def validate_name(
        self,
        value,
        field_name,
        entry_name
    ):

        value = str(
            value or ""
        ).strip()

        if not value:

            self.set_validation(
                entry_name,
                f"{field_name} wajib diisi."
            )

            return False

        if len(value) < 2:

            self.set_validation(
                entry_name,
                f"{field_name} minimal 2 karakter."
            )

            return False

        if len(value) > 100:

            self.set_validation(
                entry_name,
                f"{field_name} maksimal 100 karakter."
            )

            return False

        # --------------------------------------------------------
        # ANGKA
        # --------------------------------------------------------

        if any(
            char.isdigit()
            for char in value
        ):

            self.set_validation(
                entry_name,
                f"{field_name} tidak boleh mengandung angka."
            )

            return False

        # --------------------------------------------------------
        # HANYA SPASI
        # --------------------------------------------------------

        if not any(
            char.isalpha()
            for char in value
        ):

            self.set_validation(
                entry_name,
                f"{field_name} harus mengandung huruf."
            )

            return False

        return True

    # ============================================================
    # VALIDATE EMAIL
    # ============================================================

    def validate_email(
        self,
        email
    ):

        email = str(
            email or ""
        ).strip()

        if not email:

            self.set_validation(
                "email_entry",
                "Email wajib diisi."
            )

            return False

        if len(email) > 255:

            self.set_validation(
                "email_entry",
                "Email maksimal 255 karakter."
            )

            return False

        pattern = (
            r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
            r"@"
            r"[A-Za-z0-9]"
            r"(?:[A-Za-z0-9-]{0,61}"
            r"[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9]"
            r"(?:[A-Za-z0-9-]{0,61}"
            r"[A-Za-z0-9])?)+$"
        )

        if not re.fullmatch(
            pattern,
            email
        ):

            self.set_validation(
                "email_entry",
                "Format email tidak valid."
            )

            return False

        return True

    # ============================================================
    # VALIDATE PHONE
    # ============================================================

    def validate_phone(
        self,
        phone
    ):

        phone = str(
            phone or ""
        ).strip()

        if not phone:

            self.set_validation(
                "phone_entry",
                "Nomor HP wajib diisi."
            )

            return False

        # --------------------------------------------------------
        # CHARACTER CHECK
        # --------------------------------------------------------

        if not re.fullmatch(
            r"[0-9+\-\s()]+",
            phone
        ):

            self.set_validation(
                "phone_entry",
                "Nomor HP mengandung karakter tidak valid."
            )

            return False

        # --------------------------------------------------------
        # PLUS SIGN
        # --------------------------------------------------------

        if "+" in phone:

            if not phone.startswith("+"):

                self.set_validation(
                    "phone_entry",
                    "Tanda '+' hanya boleh berada di awal."
                )

                return False

            if phone.count("+") > 1:

                self.set_validation(
                    "phone_entry",
                    "Tanda '+' hanya boleh digunakan satu kali."
                )

                return False

        # --------------------------------------------------------
        # DIGIT COUNT
        # --------------------------------------------------------

        digits = re.sub(
            r"\D",
            "",
            phone
        )

        if len(digits) < 8:

            self.set_validation(
                "phone_entry",
                "Nomor HP minimal 8 digit."
            )

            return False

        if len(digits) > 15:

            self.set_validation(
                "phone_entry",
                "Nomor HP maksimal 15 digit."
            )

            return False

        return True

    # ============================================================
    # VALIDATE FORM
    # ============================================================

    def validate_form(self):

        self.clear_validation()

        data = self.get_form_data()

        # --------------------------------------------------------
        # FIRST NAME
        # --------------------------------------------------------

        if not self.validate_name(
            data["firstName"],
            "First Name",
            "first_name_entry"
        ):

            self.first_name_entry.focus_set()

            return False

        # --------------------------------------------------------
        # LAST NAME
        # --------------------------------------------------------

        if not self.validate_name(
            data["lastName"],
            "Last Name",
            "last_name_entry"
        ):

            self.last_name_entry.focus_set()

            return False

        # --------------------------------------------------------
        # EMAIL
        # --------------------------------------------------------

        if not self.validate_email(
            data["emailAddress"]
        ):

            self.email_entry.focus_set()

            return False

        # --------------------------------------------------------
        # PHONE
        # --------------------------------------------------------

        if not self.validate_phone(
            data["phoneNumber"]
        ):

            self.phone_entry.focus_set()

            return False

        return True

    # ============================================================
    # BUILD UPDATE DATA
    # ============================================================

    def build_update_data(
        self,
        new_data
    ):
        """
        Menyiapkan data update.

        Account lama tidak diubah jika form memang
        tidak menyediakan field Account.
        """

        return dict(new_data)

    # ============================================================
    # SAVE CONTACT
    # ============================================================

    def save_contact(self):

        if self.is_saving:
            return

        # ========================================================
        # VALIDATION
        # ========================================================

        if not self.validate_form():
            return

        new_data = self.get_form_data()

        self.is_saving = True

        self.set_saving_state()

        try:

            # ====================================================
            # EDIT
            # ====================================================

            if self.is_edit:

                self.save_edit(
                    new_data
                )

                return

            # ====================================================
            # CREATE
            # ====================================================

            self.save_create(
                new_data
            )

        except Exception as exc:

            self.handle_save_error(
                exc
            )

    # ============================================================
    # SAVE EDIT
    # ============================================================

    def save_edit(
        self,
        new_data
    ):

        contact_id = (
            self.contact.get(
                "id"
            )
        )

        if not contact_id:

            raise ValueError(
                "ID Contact tidak ditemukan."
            )

        # --------------------------------------------------------
        # DATA LAMA
        # --------------------------------------------------------

        old_data = dict(
            self.contact
        )

        # --------------------------------------------------------
        # DATA UPDATE
        # --------------------------------------------------------

        update_data = self.build_update_data(
            new_data
        )

        # --------------------------------------------------------
        # ACCOUNT ID
        #
        # Tidak diubah karena form tidak menyediakan
        # selector Account.
        # --------------------------------------------------------

        account_id = (
            self.contact.get(
                "accountId"
            )
        )

        # --------------------------------------------------------
        # API UPDATE
        # --------------------------------------------------------

        if account_id:

            updated = api.update_contact(
                contact_id,
                update_data["firstName"],
                update_data["lastName"],
                update_data["emailAddress"],
                update_data["phoneNumber"],
                account_id=account_id
            )

        else:

            updated = api.update_contact(
                contact_id,
                update_data["firstName"],
                update_data["lastName"],
                update_data["emailAddress"],
                update_data["phoneNumber"]
            )

        # --------------------------------------------------------
        # API RESULT
        # --------------------------------------------------------

        if isinstance(
            updated,
            dict
        ):

            result = dict(
                updated
            )

        else:

            result = {}

        # --------------------------------------------------------
        # FORM DATA
        # --------------------------------------------------------

        result.update(
            update_data
        )

        result["id"] = (
            result.get("id")
            or contact_id
        )

        # --------------------------------------------------------
        # PRESERVE OLD DATA
        # --------------------------------------------------------

        for key, value in old_data.items():

            if key not in result:

                result[key] = value

        # --------------------------------------------------------
        # HISTORY
        # --------------------------------------------------------

        if self.on_change:

            self.on_change(
                "update",
                old_data,
                dict(result)
            )

        # --------------------------------------------------------
        # DASHBOARD
        # --------------------------------------------------------

        self.call_success(
            result
        )

        self.is_success = True

        # --------------------------------------------------------
        # SUCCESS MESSAGE
        # --------------------------------------------------------

        self.show_success(
            "Contact berhasil diperbarui."
        )

    # ============================================================
    # SAVE CREATE
    # ============================================================

    def save_create(
        self,
        new_data
    ):

        # --------------------------------------------------------
        # API CREATE
        # --------------------------------------------------------

        created = api.create_contact(
            new_data["firstName"],
            new_data["lastName"],
            new_data["emailAddress"],
            new_data["phoneNumber"]
        )

        # --------------------------------------------------------
        # API MUST RETURN DICT
        # --------------------------------------------------------

        if not isinstance(
            created,
            dict
        ):

            raise ValueError(
                "API tidak mengembalikan "
                "data Contact dalam format dictionary."
            )

        # --------------------------------------------------------
        # ID
        # --------------------------------------------------------

        contact_id = (
            created.get(
                "id"
            )
        )

        if not contact_id:

            raise ValueError(
                "Contact berhasil dibuat, "
                "tetapi ID tidak ditemukan."
            )

        # --------------------------------------------------------
        # RESULT
        # --------------------------------------------------------

        result = dict(
            created
        )

        result.update(
            new_data
        )

        result["id"] = (
            result.get(
                "id"
            )
            or contact_id
        )

        # --------------------------------------------------------
        # HISTORY
        # --------------------------------------------------------

        if self.on_change:

            self.on_change(
                "create",
                None,
                dict(result)
            )

        # --------------------------------------------------------
        # DASHBOARD CALLBACK
        # --------------------------------------------------------

        self.call_success(
            result
        )

        self.is_success = True

        # --------------------------------------------------------
        # SUCCESS MESSAGE
        # --------------------------------------------------------

        self.show_success(
            "Contact berhasil ditambahkan."
        )

    # ============================================================
    # SUCCESS MESSAGE
    # ============================================================

    def show_success(
        self,
        message
    ):

        try:

            messagebox.showinfo(
                "Berhasil",
                message,
                parent=self.window
            )

        except tk.TclError:

            pass

        self.close()

    # ============================================================
    # SAVE ERROR
    # ============================================================

    def handle_save_error(
        self,
        exc
    ):

        if self.is_closed:
            return

        try:

            messagebox.showerror(
                "Gagal Menyimpan Contact",
                (
                    "Contact gagal disimpan.\n\n"
                    "Detail error:\n"
                    f"{exc}"
                ),
                parent=self.window
            )

        except tk.TclError:

            pass

        self.enable_save_button()

    # ============================================================
    # SAVING STATE
    # ============================================================

    def set_saving_state(self):

        try:

            self.save_button.config(
                state="disabled",
                text="Menyimpan..."
            )

            self.cancel_button.config(
                state="disabled"
            )

            self.window.update_idletasks()

        except tk.TclError:

            pass

    # ============================================================
    # ENABLE SAVE BUTTON
    # ============================================================

    def enable_save_button(self):

        self.is_saving = False

        try:

            self.cancel_button.config(
                state="normal"
            )

            if self.is_edit:

                self.save_button.config(
                    state="normal",
                    text="✓  Konfirmasi Edit"
                )

            else:

                self.save_button.config(
                    state="normal",
                    text="+  Simpan Contact"
                )

            self.save_button.configure(
                bg=self.PRIMARY
            )

        except tk.TclError:

            pass

    # ============================================================
    # SUCCESS CALLBACK
    # ============================================================

    def call_success(
        self,
        result
    ):
        """
        Menjalankan callback Dashboard.

        Mendukung dua bentuk:

            callback(result)

        dan:

            callback()
        """

        if not callable(
            self.on_success
        ):
            return

        callback = self.on_success

        # --------------------------------------------------------
        # CEK SIGNATURE
        # --------------------------------------------------------

        try:

            signature = inspect.signature(
                callback
            )

            parameters = list(
                signature.parameters.values()
            )

            accepts_argument = any(
                parameter.kind
                in (
                    parameter.POSITIONAL_ONLY,
                    parameter.POSITIONAL_OR_KEYWORD,
                    parameter.VAR_POSITIONAL
                )
                for parameter in parameters
            )

            if accepts_argument:

                callback(
                    result
                )

            else:

                callback()

        except (
            ValueError,
            TypeError
        ):

            # ----------------------------------------------------
            # Fallback
            # ----------------------------------------------------

            try:

                callback(
                    result
                )

            except TypeError:

                callback()

    # ============================================================
    # CTRL + S
    # ============================================================

    def handle_save_shortcut(
        self,
        event=None
    ):

        self.save_contact()

        return "break"

    # ============================================================
    # ESCAPE
    # ============================================================

    def handle_escape(
        self,
        event=None
    ):

        self.close()

        return "break"

    # ============================================================
    # CLOSE
    # ============================================================

    def close(self):

        if self.is_closed:
            return

        self.is_closed = True

        try:

            self.window.grab_release()

        except tk.TclError:

            pass

        try:

            self.window.destroy()

        except tk.TclError:

            pass

    # ============================================================
    # VALUE FORMATTER
    # ============================================================

    @staticmethod
    def val(
        value
    ):

        if value is None:
            return "-"

        if isinstance(
            value,
            str
        ):

            if not value.strip():
                return "-"

        return str(value)


# ================================================================
# TEST MODE
# ================================================================

if __name__ == "__main__":

    root = tk.Tk()

    root.title(
        "Contact Form Test"
    )

    root.geometry(
        "450x300"
    )

    root.configure(
        bg="#F4F6F9"
    )

    # ============================================================
    # TEST CALLBACK
    # ============================================================

    def test_success(
        contact=None
    ):

        print()
        print("=" * 60)
        print("CONTACT SUCCESS")
        print("=" * 60)
        print(contact)
        print("=" * 60)
        print()

    # ============================================================
    # TEST ADD
    # ============================================================

    tk.Button(
        root,

        text="Tambah Contact",

        command=lambda: ContactForm(
            root,
            on_success=test_success
        ),

        font=(
            "Segoe UI",
            10,
            "bold"
        ),

        bg="#2563EB",
        fg="#FFFFFF",

        activebackground="#1D4ED8",
        activeforeground="#FFFFFF",

        relief="flat",
        bd=0,

        padx=18,
        pady=10,

        cursor="hand2"
    ).pack(
        pady=(50, 10)
    )

    # ============================================================
    # TEST EDIT
    # ============================================================

    dummy_contact = {

        "id": "TEST_CONTACT_ID",

        "firstName": "Yanto",

        "lastName": "Rahma",

        "emailAddress": "yanto@gmail.com",

        "phoneNumber": "+628222222222",

        "accountName": "-",

        "accountId": ""
    }

    tk.Button(
        root,

        text="Edit Contact",

        command=lambda: ContactForm(
            root,
            contact_data=dummy_contact,
            on_success=test_success
        ),

        font=(
            "Segoe UI",
            10,
            "bold"
        ),

        bg="#10B981",
        fg="#FFFFFF",

        activebackground="#059669",
        activeforeground="#FFFFFF",

        relief="flat",
        bd=0,

        padx=18,
        pady=10,

        cursor="hand2"
    ).pack()

    root.mainloop()