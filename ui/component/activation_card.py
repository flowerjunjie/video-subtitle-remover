# -*- coding: utf-8 -*-
"""
激活卡组件 - 用户侧激活码输入和状态展示
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QFrame)
from PySide6 import QtWidgets
from qfluentwidgets import (CardWidget, LineEdit, PrimaryPushButton,
                           FluentIcon, InfoBar, InfoBarPosition)

from backend.config import config, tr
from backend.tools.activation import (
    check_activation_status, activate_code, get_machine_id, load_activation_status
)


class ActivationCard(CardWidget):
    """用户侧激活卡"""

    activation_success_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("ActivationCard")
        self._init_ui()
        self._check_initial_status()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("激活码")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # 状态显示
        self.status_label = QLabel("未激活")
        self.status_label.setObjectName("status_label")
        self.status_label.setStyleSheet("font-size: 14px; color: #e53935;")
        layout.addWidget(self.status_label)

        # 到期提示
        self.expiry_label = QLabel("")
        self.expiry_label.setObjectName("expiry_label")
        self.expiry_label.setStyleSheet("color: #888; font-size: 12px;")
        self.expiry_label.setVisible(False)
        layout.addWidget(self.expiry_label)

        # 激活码输入
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.code_input = LineEdit()
        self.code_input.setPlaceholderText("输入激活码 (格式: VSR-XXXX-XXXX-XXXX-XXXX)")
        self.code_input.textChanged.connect(self._on_code_changed)
        input_layout.addWidget(self.code_input)

        self.activate_btn = PrimaryPushButton("激活")
        self.activate_btn.setIcon(FluentIcon.SEND)
        self.activate_btn.clicked.connect(self._do_activate)
        self.activate_btn.setEnabled(False)
        input_layout.addWidget(self.activate_btn)

        layout.addLayout(input_layout)

    def _check_initial_status(self):
        """检查初始激活状态"""
        is_active, days = check_activation_status()

        if is_active:
            self._show_active_state(days)
        else:
            self._show_inactive_state()

    def _show_active_state(self, days_remaining: int):
        """显示已激活状态"""
        self.status_label.setText(f"已激活 (剩余 {days_remaining} 天)")
        self.status_label.setStyleSheet("font-size: 14px; color: #4CAF50;")
        self.expiry_label.setVisible(True)

        status = load_activation_status()
        if status.get("expires_at"):
            self.expiry_label.setText(f"到期日: {status['expires_at'][:10]}")

        self.code_input.setVisible(False)
        self.activate_btn.setVisible(False)

    def _show_inactive_state(self):
        """显示未激活状态"""
        self.status_label.setText("未激活")
        self.status_label.setStyleSheet("font-size: 14px; color: #e53935;")
        self.expiry_label.setVisible(False)
        self.code_input.setVisible(True)
        self.activate_btn.setVisible(True)
        self.code_input.clear()
        self.activate_btn.setEnabled(False)

    def _on_code_changed(self, text: str):
        """激活码输入变化"""
        text = text.strip().upper()
        # 格式化：自动添加 VSR- 前缀和连字符
        if len(text) == 16 and not text.startswith("VSR-"):
            text = f"VSR-{text[:4]}-{text[4:8]}-{text[8:12]}-{text[12:16]}"

        if text != self.code_input.text():
            self.code_input.setText(text)

        self.activate_btn.setEnabled(len(text) == 23 and text.startswith("VSR-"))

    def _do_activate(self):
        """执行激活"""
        code = self.code_input.text().strip()

        if not code:
            InfoBar.warning("请输入激活码", "", position=InfoBarPosition.TOP, parent=self)
            return

        success, msg, entry = activate_code(code)

        if success:
            InfoBar.success("激活成功", f"您的授权已激活，有效期至 {entry['expires_at'][:10]}", position=InfoBarPosition.TOP, parent=self)
            self.activation_success_signal.emit()
            self._show_active_state(entry['months'] * 30)
        else:
            InfoBar.error("激活失败", msg, position=InfoBarPosition.TOP, parent=self)

    def check_status(self):
        """外部检查状态（供定时调用）"""
        is_active, days = check_activation_status()
        if is_active:
            self._show_active_state(days)
        else:
            self._show_inactive_state()