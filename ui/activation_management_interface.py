# -*- coding: utf-8 -*-
"""
激活码管理界面
功能：激活码生成、列表、统计
"""
import sys
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QLabel, QLineEdit, QSpinBox, QComboBox, QDialog,
                               QDialogButtonBox, QMessageBox, QScrollArea, QGridLayout,
                               CardWidget, QGroupBox)
from PySide6 import QtWidgets
from qfluentwidgets import (FluentIcon, PrimaryPushButton, CardWidget, LineEdit,
                           SpinBox, ComboBox, PrimaryPushButton, InfoBar, InfoBarPosition)

from backend.config import config, tr
from backend.tools.activation import (
    generate_batch_codes, get_all_codes, delete_activation_code,
    get_code_stats, cleanup_expired_codes, PRICE_PER_MONTH
)


class ActivationManagementInterface(QWidget):
    """激活码管理主界面"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("ActivationManagementInterface")
        self.current_page = 0
        self.page_size = 20
        self.filter_status = "all"
        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 统计卡片区域
        stats_group = self._create_stats_section()
        main_layout.addWidget(stats_group)

        # 生成激活码区域
        generate_group = self._create_generate_section()
        main_layout.addWidget(generate_group)

        # 筛选区域
        filter_layout = self._create_filter_section()
        main_layout.addLayout(filter_layout)

        # 激活码列表
        self.table = self._create_table()
        main_layout.addWidget(self.table, 1)

        # 分页控制
        pagination_layout = self._create_pagination()
        main_layout.addLayout(pagination_layout)

    def _create_stats_section(self) -> QGroupBox:
        """创建统计卡片区域"""
        group = QGroupBox("统计数据")
        layout = QHBoxLayout(group)
        layout.setSpacing(16)

        self.stats_labels = {}
        stats_items = [
            ("total", "总生成数"),
            ("unused", "未使用"),
            ("active", "使用中"),
            ("expired", "已过期"),
            ("revenue", "总收益"),
        ]

        for key, label in stats_items:
            card = CardWidget()
            card_layout = QVBoxLayout(card)
            card_layout.setAlignment(Qt.AlignCenter)

            value_label = QLabel("0")
            value_label.setObjectName(f"stats_{key}")
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet("font-size: 24px; font-weight: bold;")

            name_label = QLabel(label)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet("color: #888;")

            card_layout.addWidget(value_label)
            card_layout.addWidget(name_label)

            layout.addWidget(card)
            self.stats_labels[key] = value_label

        # 刷新按钮
        refresh_btn = PrimaryPushButton("刷新统计")
        refresh_btn.setIcon(FluentIcon.UPDATE)
        refresh_btn.clicked.connect(self.refresh_stats)
        layout.addWidget(refresh_btn)

        return group

    def _create_generate_section(self) -> QGroupBox:
        """创建激活码生成区域"""
        group = QGroupBox("生成激活码")
        layout = QHBoxLayout(group)
        layout.setSpacing(16)

        # 数量输入
        count_layout = QVBoxLayout()
        count_label = QLabel("生成数量")
        self.count_spin = SpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(1)
        count_layout.addWidget(count_label)
        count_layout.addWidget(self.count_spin)
        layout.addLayout(count_layout)

        # 月数选择
        month_layout = QVBoxLayout()
        month_label = QLabel("月数")
        self.month_combo = ComboBox()
        self.month_combo.addItems(["1个月 (¥9.9)", "3个月 (¥27.9)", "6个月 (¥55.9)", "12个月 (¥99.9)"])
        self.month_combo.setObjectName("month_combo")
        month_layout.addWidget(month_label)
        month_layout.addWidget(self.month_combo)
        layout.addLayout(month_layout)

        # 价格提示
        price_layout = QVBoxLayout()
        price_layout.addWidget(QLabel(""))
        price_hint = QLabel("¥9.9/月 起")
        price_hint.setStyleSheet("color: #666; font-size: 12px;")
        price_layout.addWidget(price_hint)
        layout.addLayout(price_layout)

        # 生成按钮
        generate_btn = PrimaryPushButton("生成")
        generate_btn.setIcon(FluentIcon.ADD)
        generate_btn.clicked.connect(self.generate_codes)
        layout.addWidget(generate_btn)

        return group

    def _create_filter_section(self) -> QHBoxLayout:
        """创建筛选区域"""
        layout = QHBoxLayout()

        filter_label = QLabel("筛选")
        layout.addWidget(filter_label)

        self.filter_combo = ComboBox()
        self.filter_combo.addItems(["全部", "未使用", "使用中", "已过期"])
        self.filter_combo.currentTextChanged.connect(self.on_filter_changed)
        layout.addWidget(self.filter_combo)

        layout.addStretch()

        return layout

    def _create_table(self) -> QTableWidget:
        """创建激活码列表表格"""
        table = QTableWidget()
        table.setObjectName("activation_table")
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["序号", "激活码", "月数", "价格", "状态", "操作"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        table.setColumnWidth(2, 60)
        table.setColumnWidth(3, 80)
        table.setColumnWidth(4, 80)
        table.setColumnWidth(5, 80)
        table.setAlternatingRowColors(True)
        return table

    def _create_pagination(self) -> QHBoxLayout:
        """创建分页控制"""
        layout = QHBoxLayout()

        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.prev_page)
        layout.addWidget(self.prev_btn)

        self.page_label = QLabel("第 1 页")
        layout.addWidget(self.page_label)

        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        layout.addWidget(self.next_btn)

        layout.addStretch()

        return layout

    def refresh_stats(self):
        """刷新统计数据"""
        cleanup_expired_codes()
        stats = get_code_stats()

        self.stats_labels["total"].setText(str(stats["total"]))
        self.stats_labels["unused"].setText(str(stats["unused"]))
        self.stats_labels["active"].setText(str(stats["active"]))
        self.stats_labels["expired"].setText(str(stats["expired"]))
        self.stats_labels["revenue"].setText(f"¥{stats['total_revenue']:.1f}")

        self.load_table()

    def generate_codes(self):
        """生成激活码"""
        count = self.count_spin.value()
        month_text = self.month_combo.currentText()
        months = int(month_text.split("个月")[0])

        try:
            entries = generate_batch_codes(count, months)
            self.refresh_stats()

            codes_preview = "\n".join([e["code"] for e in entries[:5]])
            if len(entries) > 5:
                codes_preview += f"\n... 还有 {len(entries) - 5} 个"

            QMessageBox.information(
                self,
                "生成成功",
                f"成功生成 {len(entries)} 个激活码：\n\n{codes_preview}"
            )
        except Exception as e:
            QMessageBox.critical(self, "生成失败", f"生成激活码时出错：\n{str(e)}")

    def on_filter_changed(self, text: str):
        """筛选变更"""
        self.filter_status = text
        self.current_page = 0
        self.load_table()

    def load_table(self):
        """加载激活码列表"""
        all_codes = get_all_codes()

        # 筛选
        if self.filter_status == "未使用":
            codes = [c for c in all_codes if c["status"] == "unused"]
        elif self.filter_status == "使用中":
            codes = [c for c in all_codes if c["status"] == "active"]
        elif self.filter_status == "已过期":
            codes = [c for c in all_codes if c["status"] == "expired"]
        else:
            codes = all_codes

        # 分页
        codes.reverse()  # 最新的在前
        total_pages = max(1, (len(codes) + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, total_pages - 1)

        start = self.current_page * self.page_size
        end = start + self.page_size
        page_codes = codes[start:end]

        # 填充表格
        self.table.setRowCount(len(page_codes))
        for row, entry in enumerate(page_codes):
            idx = start + row + 1

            self.table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.table.item(row, 0).setTextAlignment(Qt.AlignCenter)

            code_item = QTableWidgetItem(entry["code"])
            code_item.setToolTip(entry["code"])
            self.table.setItem(row, 1, code_item)

            self.table.setItem(row, 2, QTableWidgetItem(f"{entry['months']}"))
            self.table.item(row, 2).setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row, 3, QTableWidgetItem(f"¥{entry.get('price', 0):.1f}"))
            self.table.item(row, 3).setTextAlignment(Qt.AlignCenter)

            status = entry["status"]
            status_text = {"unused": "未使用", "active": "使用中", "expired": "已过期"}.get(status, status)
            status_color = {"unused": "#4CAF50", "active": "#2196F3", "expired": "#9E9E9E"}.get(status, "#666")
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(Qt.black)
            self.table.setItem(row, 4, status_item)
            self.table.item(row, 4).setTextAlignment(Qt.AlignCenter)

            delete_btn = QPushButton("删除")
            delete_btn.setStyleSheet("background-color: #f44336; color: white; border: none; padding: 4px 8px;")
            delete_btn.clicked.connect(lambda _, c=entry["code"]: self.delete_code(c))
            self.table.setCellWidget(row, 5, delete_btn)

        # 更新分页标签
        self.page_label.setText(f"第 {self.current_page + 1} / {total_pages} 页")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

    def delete_code(self, code: str):
        """删除激活码"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除激活码 {code} 吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            success, msg = delete_activation_code(code)
            if success:
                InfoBar.success("删除成功", msg, position=InfoBarPosition.TOP, parent=self)
                self.refresh_stats()
            else:
                InfoBar.error("删除失败", msg, position=InfoBarPosition.TOP, parent=self)

    def prev_page(self):
        """上一页"""
        if self.current_page > 0:
            self.current_page -= 1
            self.load_table()

    def next_page(self):
        """下一页"""
        self.current_page += 1
        self.load_table()