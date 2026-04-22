#!/usr/bin/env python3

import sys
import json
import random
import os
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QInputDialog, QMessageBox, QMenu, QAction
from PyQt5.QtCore import Qt, QRect, QTimer
from PyQt5.QtGui import QPainter, QColor, QFont, QPixmap, QPen, QIcon, QLinearGradient
import base64
import tempfile

# ============== KART SINIFI ==============
@dataclass
class Card:
    id: int
    pair_id: int
    icon: str
    is_flipped: bool = False
    is_matched: bool = False
    rect: QRect = field(default_factory=QRect)
    hover: bool = False

SELECTED_ICONS = [
    '🦁', '🐯', '🐻', '🐼', '🍎', '🍊', '⚽', '🏀',
    '🎵', '🎸', '🚗', '✈️', '☀️', '❄️', '⌚', '💻',
    '🌲', '🌸', '🎮', '🎯', '📱', '🎬', '🧩', '🎭'
]

# ============== SKOR YÖNETİCİSİ ==============
class ScoreManager:
    """Skor sistemi - her kart adedi için ayrı skor"""
    DEFAULT_GRIDS = ('4x4', '4x6', '5x6', '4x8', '6x8')

    def __init__(self):
        self.scores_file = Path.home() / '.local' / 'share' / 'memory-game' / 'scores_steps.json'
        self.scores_file.parent.mkdir(parents=True, exist_ok=True)
        self.leaderboard = self.load_scores()
    
    def load_scores(self):
        if self.scores_file.exists():
            try:
                with open(self.scores_file, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                    for grid in self.DEFAULT_GRIDS:
                        data.setdefault(grid, [])
                    return data
            except (json.JSONDecodeError, OSError):
                return {grid: [] for grid in self.DEFAULT_GRIDS}
        return {grid: [] for grid in self.DEFAULT_GRIDS}
    
    def add_score(self, player_name, score, moves, matched_pairs, grid_size, duration_seconds):
        if grid_size not in self.leaderboard:
            self.leaderboard[grid_size] = []
        
        entry = {
            'name': player_name,
            'moves': moves,
            'matched': matched_pairs,
            'duration': duration_seconds,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        
        self.leaderboard[grid_size].append(entry)
        self.leaderboard[grid_size] = sorted(
            self.leaderboard[grid_size], key=lambda x: (x.get('moves', 10**9), x.get('duration', 10**9))
        )[:10]
        
        try:
            with open(self.scores_file, 'w', encoding='utf-8') as f:
                json.dump(self.leaderboard, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Skor kaydında hata: {e}")
        
        return self.leaderboard[grid_size]
    
    def get_top_scores(self, grid_size='6x8'):
        return self.leaderboard.get(grid_size, [])


class GameWidget(QWidget):
    def __init__(self, player_name, score_manager, grid_size='6x8'):
        super().__init__()
        
        self.player_name = player_name
        self.score_manager = score_manager
        self.grid_size = grid_size
        
        self.rows, self.cols = self.parse_grid(grid_size)
        self.total_pairs = (self.rows * self.cols) // 2
        
        self.cards = []
        self.first_flipped = -1
        self.second_flipped = -1
        self.score = 0
        self.moves = 0
        self.matched_pairs = 0
        self.elapsed_seconds = 0
        self.game_active = True
        self.game_finished = False
        self.timer_running = False
        
        # Arka plan
        self.background_image = None
        self.blurred_background = None
        self.load_or_create_background()
        
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_match)

        self.game_timer = QTimer()
        self.game_timer.setInterval(1000)
        self.game_timer.timeout.connect(self.tick_time)
        
        self.reset_btn_rect = QRect()
        self.reset_btn_hover = False
        self.sidebar_width = 320
        self.sidebar_min_width = 250
        self.sidebar_max_width = 560
        self.sidebar_resize_margin = 8
        self.sidebar_resizing = False
        self.top_panel_height = 70
        
        self.initialize_cards()
        self.setMinimumSize(1400, 900)
    
    def parse_grid(self, grid_size):
        sizes = {'4x4': (4, 4), '4x6': (4, 6), '5x6': (5, 6), '4x8': (4, 8), '6x8': (6, 8)}
        return sizes.get(grid_size, (6, 8))
    
    def load_or_create_background(self):
        """Qt ile modern, performanslı gradient arka plan"""
        pixmap = QPixmap(1200, 900)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        gradient = QLinearGradient(0, 0, 1200, 900)
        gradient.setColorAt(0.0, QColor(248, 250, 252))
        gradient.setColorAt(1.0, QColor(234, 240, 246))
        painter.fillRect(0, 0, 1200, 900, gradient)
        painter.end()
        self.background_image = pixmap
        self.blurred_background = pixmap.copy()

    def tick_time(self):
        self.elapsed_seconds += 1
        self.update()

    def format_time(self):
        minutes, seconds = divmod(self.elapsed_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def initialize_cards(self):
        self.cards = []
        total_cards = self.rows * self.cols
        needed_pairs = total_cards // 2
        icons = SELECTED_ICONS[:needed_pairs] * 2
        random.shuffle(icons)
        
        self.total_pairs = needed_pairs
        
        for i in range(total_cards):
            icon = icons[i]
            pair_id = SELECTED_ICONS.index(icon)
            card = Card(i, pair_id, icon)
            self.cards.append(card)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Arka plan (sağ taraf) - beyaz oyun alanı
        bg_x = self.sidebar_width
        game_rect = QRect(bg_x, 0, self.width() - bg_x, self.height())
        painter.fillRect(game_rect, QColor("#ffffff"))
        painter.setPen(QPen(QColor("#cccccc"), 1))
        # Skor tabelası ile bilgi bölümü arasında çizgi istemediğin için
        # yalnızca sağ ve alt sınırı çiziyoruz.
        painter.drawLine(game_rect.right(), game_rect.top(), game_rect.right(), game_rect.bottom())
        painter.drawLine(game_rect.left(), game_rect.bottom(), game_rect.right(), game_rect.bottom())
        
        # SOL PANEL - Modern Office Style
        self.draw_modern_sidebar(painter, bg_x)
        
        # Kartlar (sağ taraf) - ayraçlara eşit dış boşlukla yerleşim
        cols = self.cols
        rows = self.rows
        outer_padding = 14
        card_gap = 6
        cards_area_x = bg_x + outer_padding
        cards_area_y = self.top_panel_height + outer_padding
        cards_area_w = (self.width() - bg_x) - (outer_padding * 2)
        cards_area_h = (self.height() - self.top_panel_height) - (outer_padding * 2)
        card_w = max(10, (cards_area_w - (card_gap * (cols - 1))) // cols)
        card_h = max(10, (cards_area_h - (card_gap * (rows - 1))) // rows)
        start_x = cards_area_x
        start_y = cards_area_y
        
        for i, card in enumerate(self.cards):
            row, col = i // cols, i % cols
            x = start_x + col * (card_w + card_gap)
            y = start_y + row * (card_h + card_gap)
            
            card.rect = QRect(x, y, card_w, card_h)
            
            # Kart tasarımı
            if card.is_matched:
                painter.fillRect(card.rect, QColor(76, 175, 80))
            elif card.is_flipped:
                painter.fillRect(card.rect, QColor(25, 118, 210))
            else:
                painter.fillRect(card.rect, QColor("#d9d9d9"))
            
            # Kart kenarı 1px
            painter.setPen(QPen(QColor("#cccccc"), 1))
            painter.drawRoundedRect(card.rect, 6, 6)
            
            # İcon
            if card.is_flipped or card.is_matched:
                painter.setFont(QFont("Arial", 48))
                painter.setPen(Qt.white if card.is_flipped or card.is_matched else QColor(100, 100, 100))
                painter.drawText(card.rect, Qt.AlignCenter, card.icon)
        
        # Üst Panel - Modern Office Style
        self.draw_top_panel(painter, bg_x)

    def draw_modern_sidebar(self, painter, width):
        """Modern Office-style sidebar"""
        # Arka plan - skor tabelası
        painter.fillRect(0, 0, width, self.height(), QColor("#f3f3f3"))
        
        # Sağ sınır: bilgi bölümünde görünmesin diye 70px sonrası çizilir
        painter.setPen(QPen(QColor("#cccccc"), 1))
        painter.drawLine(width - 1, 70, width - 1, self.height())
        
        # Başlık
        painter.setPen(QColor(25, 103, 210))
        painter.setFont(QFont("Segoe UI", 16, QFont.Bold))
        painter.drawText(15, 35, f"🏆 Sıralama ({self.grid_size})")
        
        # Alt çizgi
        painter.setPen(QPen(QColor("#cccccc"), 1))
        painter.drawLine(15, 45, width - 15, 45)
        
        # Başlık satırı
        painter.setPen(QColor(100, 100, 100))
        painter.setFont(QFont("Segoe UI", 9, QFont.Normal))
        moves_col_x = 190
        duration_col_x = 240
        painter.drawText(15, 65, "Sıra")
        painter.drawText(50, 65, "Oyuncu")
        painter.drawText(moves_col_x, 65, "Adım")
        painter.drawText(duration_col_x, 65, "Süre")
        
        # Skor listesi - grid boyutuna göre
        scores = self.score_manager.get_top_scores(self.grid_size)
        y_pos = 85
        
        painter.setFont(QFont("Segoe UI", 10, QFont.Normal))
        
        for rank, entry in enumerate(scores[:10], 1):
            # Arka plan - hover
            if rank % 2 == 0:
                painter.fillRect(10, y_pos - 12, width - 20, 20, QColor("#f3f3f3"))
            
            # Medal resimleri
            medals = ['🥇', '🥈', '🥉']
            medal = medals[rank - 1] if rank <= 3 else f"{rank}."
            
            painter.setPen(QColor(33, 33, 33))
            painter.drawText(15, y_pos, medal)
            
            # Oyuncu adı (kısalt)
            name = entry['name'][:15]
            painter.drawText(50, y_pos, name)
            
            # Adım sayısı
            painter.setPen(QColor(25, 103, 210))
            painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
            painter.drawText(moves_col_x, y_pos, str(entry.get('moves', '-')))
            painter.setPen(QColor(120, 120, 120))
            painter.setFont(QFont("Segoe UI", 9, QFont.Normal))
            painter.drawText(duration_col_x, y_pos, f"{entry.get('duration', 0)}sn")
            
            painter.setFont(QFont("Segoe UI", 10, QFont.Normal))
            painter.setPen(QColor(33, 33, 33))
            
            y_pos += 25

    def clamp_sidebar_width(self, desired_width):
        max_width = min(self.sidebar_max_width, self.width() - 360)
        max_width = max(max_width, self.sidebar_min_width)
        return max(self.sidebar_min_width, min(desired_width, max_width))

    def is_on_sidebar_edge(self, pos):
        return abs(pos.x() - self.sidebar_width) <= self.sidebar_resize_margin

    def draw_top_panel(self, painter, start_x):
        """Modern Office-style üst panel"""
        panel_height = self.top_panel_height
        
        # Arka plan - bilgi bölümü
        painter.fillRect(start_x, 0, self.width() - start_x, panel_height, QColor("#f3f3f3"))
        
        # Alt sınır
        painter.setPen(QPen(QColor("#cccccc"), 1))
        painter.drawLine(start_x, panel_height - 1, self.width(), panel_height - 1)
        
        # Oyuncu adı - başlık
        painter.setPen(QColor(25, 103, 210))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(start_x + 15, 20, f"👤 {self.player_name}")
        
        # Adımlar - sayı
        painter.setPen(QColor(100, 100, 100))
        painter.setFont(QFont("Segoe UI", 10, QFont.Normal))
        painter.drawText(start_x + 15, 45, f"Adımlar:")
        
        painter.setPen(QColor(25, 103, 210))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        painter.drawText(start_x + 100, 45, str(self.moves))
        
        # Eşleştirmeler - sayı
        painter.setPen(QColor(100, 100, 100))
        painter.setFont(QFont("Segoe UI", 10, QFont.Normal))
        painter.drawText(start_x + 200, 45, f"Eşleştirmeler:")
        
        painter.setPen(QColor(25, 103, 210))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        painter.drawText(start_x + 330, 45, f"{self.matched_pairs}/{self.total_pairs}")

        # Süre - canlı güncellenir
        painter.setPen(QColor(100, 100, 100))
        painter.setFont(QFont("Segoe UI", 10, QFont.Normal))
        painter.drawText(start_x + 430, 45, "Süre:")
        painter.setPen(QColor(25, 103, 210))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        painter.drawText(start_x + 485, 45, self.format_time())
        
        # Reset Butonu - Modern Office Style
        self.draw_reset_button(painter)

    def draw_reset_button(self, painter):
        """Modern Office-style reset butonu"""
        self.reset_btn_rect = QRect(self.width() - 180, 12, 160, 46)
        
        # Gölge
        painter.fillRect(self.reset_btn_rect.adjusted(0, 2, 2, 2), QColor(0, 0, 0, 30))
        
        # Arka plan - hover kontrolü
        if self.reset_btn_hover:
            painter.fillRect(self.reset_btn_rect, QColor(41, 128, 185))  # Daha koyu mavi
        else:
            painter.fillRect(self.reset_btn_rect, QColor(52, 152, 219))  # Mavi
        
        # Border
        painter.setPen(QPen(QColor(25, 103, 210), 1))
        painter.drawRoundedRect(self.reset_btn_rect, 4, 4)
        
        # Yazı
        painter.setPen(Qt.white)
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(self.reset_btn_rect, Qt.AlignCenter, "↻  Yeniden Başlat")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_on_sidebar_edge(event.pos()):
            self.sidebar_resizing = True
            self.setCursor(Qt.SizeHorCursor)
            return

        if self.reset_btn_rect.contains(event.pos()):
            self.reset_game()
            return
        
        if not self.game_active or (self.first_flipped != -1 and self.second_flipped != -1):
            return
        
        for i, card in enumerate(self.cards):
            if card.rect.contains(event.pos()) and not card.is_flipped and not card.is_matched:
                card.is_flipped = True
                
                if self.first_flipped == -1:
                    self.first_flipped = i
                elif self.second_flipped == -1:
                    self.second_flipped = i
                    self.moves += 1
                    if not self.timer_running:
                        self.game_timer.start()
                        self.timer_running = True
                    self.game_active = False
                    self.check_timer.start(1000)
                
                self.update()
                return

    def mouseMoveEvent(self, event):
        """Hover efekti"""
        if self.sidebar_resizing:
            self.sidebar_width = self.clamp_sidebar_width(event.pos().x())
            self.update()
            return

        if self.is_on_sidebar_edge(event.pos()):
            self.setCursor(Qt.SizeHorCursor)
            return

        hover = self.reset_btn_rect.contains(event.pos())
        if hover != self.reset_btn_hover:
            self.reset_btn_hover = hover
            self.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
            self.update()
        elif not hover:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.sidebar_resizing:
            self.sidebar_resizing = False
            self.setCursor(Qt.ArrowCursor)

    def check_match(self):
        self.check_timer.stop()
        
        first_card = self.cards[self.first_flipped]
        second_card = self.cards[self.second_flipped]
        
        if first_card.pair_id == second_card.pair_id:
            first_card.is_matched = True
            second_card.is_matched = True
            self.matched_pairs += 1
            
            if self.matched_pairs == self.total_pairs:
                self.game_active = False
                if self.timer_running:
                    self.game_timer.stop()
                    self.timer_running = False
                self.save_and_show_result()
        else:
            first_card.is_flipped = False
            second_card.is_flipped = False
        
        self.first_flipped = -1
        self.second_flipped = -1
        self.game_active = True
        
        self.update()

    def save_and_show_result(self):
        """Skoru kaydet ve sonuç göster"""
        self.score_manager.add_score(
            self.player_name,
            0,
            self.moves,
            self.matched_pairs,
            self.grid_size,
            self.elapsed_seconds
        )
        
        result_text = f"""
Tebrikler {self.player_name}!

🎯 Toplam Adımlar: {self.moves}
✨ Eşleştirmeler: {self.matched_pairs}/{self.total_pairs}
⏱ Süre: {self.format_time()}

📊 {self.grid_size} Sıralamaya Kaydedildi!
"""
        
        parent = self.parent()
        if parent:
            parent.show_completion(result_text)

    def reset_game(self):
        self.moves = 0
        self.matched_pairs = 0
        self.elapsed_seconds = 0
        self.game_active = True
        self.game_finished = False
        if self.timer_running:
            self.game_timer.stop()
            self.timer_running = False
        self.first_flipped = -1
        self.second_flipped = -1
        
        self.initialize_cards()
        self.update()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Varsayılan grid boyutu
        self.grid_size = '6x8'
        
        # Oyuncu adını sor
        self.player_name = self.get_player_name()
        if not self.player_name:
            sys.exit(0)
        
        self.setWindowTitle(f"Bellek Oyunu - {self.player_name} - {self.grid_size}")
        self.setGeometry(50, 50, 1400, 900)
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; }
            QMenuBar { background-color: #f3f3f3; border-bottom: 1px solid #cccccc; }
            QMenuBar::item { padding: 6px 10px; border-radius: 4px; }
            QMenuBar::item:selected { background: #e6e6e6; }
            QMenu { background-color: #f3f3f3; border: 1px solid #cccccc; }
            QMenu::item { padding: 6px 18px; }
            QMenu::item:selected { background-color: #e6e6e6; color: #222222; }
        """)
        
        # Icon ayarla (kod icinde)
        try:
            icon_bytes = base64.b64decode("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")
            fd, tmp_path = tempfile.mkstemp(suffix='.png')
            os.write(fd, icon_bytes)
            os.close(fd)
            self.setWindowIcon(QIcon(tmp_path))
        except Exception:
            pass
        self.score_manager = ScoreManager()
        
        # Menü çubuğu oluştur
        self.create_menu_bar()
        
        # Oyun widget'ı
        self.game_widget = GameWidget(self.player_name, self.score_manager, self.grid_size)
        self.game_widget.setParent(self)
        self.setCentralWidget(self.game_widget)
    
    def create_menu_bar(self):
        """Menü çubuğu oluştur"""
        menubar = self.menuBar()
        
        # Oyun menüsü
        game_menu = menubar.addMenu("🎮 Oyun")
        
        # Yeni oyun
        new_action = QAction("🆕 Yeni Oyun", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_game)
        game_menu.addAction(new_action)
        
        # Yeniden başlat
        restart_action = QAction("🔄 Yeniden Başlat", self)
        restart_action.setShortcut("Ctrl+R")
        restart_action.triggered.connect(self.restart_game)
        game_menu.addAction(restart_action)
        
        game_menu.addSeparator()
        
        # Kart adedi alt menüsü
        grid_menu = QMenu("📊 Kart Adedi", self)
        
        for label, size in [("4x4 (16 kart)", "4x4"), ("4x6 (24 kart)", "4x6"),
                          ("5x6 (30 kart)", "5x6"), ("4x8 (32 kart)", "4x8"),
                          ("6x8 (48 kart)", "6x8")]:
            action = QAction(label, self)
            action.triggered.connect(lambda checked, s=size: self.change_grid_size(s))
            grid_menu.addAction(action)
        
        game_menu.addMenu(grid_menu)
        
        game_menu.addSeparator()
        
        reset_action = QAction("🗑 Skorları Sıfırla", self)
        reset_action.triggered.connect(self.reset_scores)
        game_menu.addAction(reset_action)
        
        # Çıkış
        exit_action = QAction("✖ Çıkış", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        game_menu.addAction(exit_action)
        
        # Oyuncu menüsü
        player_menu = menubar.addMenu("👤 Oyuncu")
        
        name_action = QAction("📝 İsim Değiştir", self)
        name_action.triggered.connect(self.change_name)
        player_menu.addAction(name_action)
        
        
        help_menu = menubar.addMenu("❓ Yardım")
        
        help_action = QAction("📖 Nasıl Oynanır", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)
    
    def new_game(self):
        """Yeni oyun"""
        name, ok = QInputDialog.getText(self, "🆕 Yeni Oyun", "Oyuncu adı:", text=self.player_name)
        if ok and name.strip():
            self.player_name = name.strip()
            self.restart_game()
    
    def restart_game(self):
        """Oyunu yeniden başlat"""
        self.game_widget = GameWidget(self.player_name, self.score_manager, self.grid_size)
        self.setCentralWidget(self.game_widget)
        self.setWindowTitle(f"Bellek Oyunu - {self.player_name} - {self.grid_size}")
    
    def reset_scores(self):
        """Skorları sıfırla"""
        reply = QMessageBox.question(self, "Skorları Sıfırla", 
            "Tüm skorları silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.score_manager.leaderboard = {grid: [] for grid in self.score_manager.DEFAULT_GRIDS}
            try:
                with open(self.score_manager.scores_file, 'w', encoding='utf-8') as f:
                    json.dump(self.score_manager.leaderboard, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
            if self.game_widget:
                self.game_widget.update()
    
    def show_help(self):
        """Yardım göster"""
        help_text = """🧠 Bellek Oyunu v2.0

Bir kart eşleştirme oyunu.

Nasıl Oynanır:
• Her kartın bir eşi var
• Kartlara tıklayarak çevirin
• Aynı ikonlu kartları eşleştirin
• En az hamlede ve en kısa sürede kazanmaya çalışın!

Platform: Linux KDE uyumlu"""

        QMessageBox.information(self, "Yardım", help_text)
    
    def change_grid_size(self, grid_size):
        """Grid boyutunu değiştir"""
        self.grid_size = grid_size
        self.restart_game()
    
    def change_name(self):
        """İsim değiştir"""
        name, ok = QInputDialog.getText(self, "👤 Oyuncu", "Yeni isminiz:", text=self.player_name)
        if ok and name.strip():
            self.player_name = name.strip()
            self.setWindowTitle(f"Bellek Oyunu - {self.player_name} - {self.grid_size}")
            if hasattr(self, 'game_widget') and self.game_widget:
                self.game_widget.player_name = self.player_name
                self.game_widget.update()
    
    def get_player_name(self):
        """Oyuncu adını sor"""
        name, ok = QInputDialog.getText(None, "🎮 Hoş Geldiniz", "Adınızı girin:", text="Oyuncu")
        if ok and name.strip():
            return name.strip()
        return None

    def show_completion(self, message):
        """Oyun tamamlanma mesajı"""
        QMessageBox.information(self, "✅ Oyun Bitti!", message)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
