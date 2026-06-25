# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'manage_models_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

class Ui_ManageModelsDialog(object):
    def setupUi(self, ManageModelsDialog):
        if not ManageModelsDialog.objectName():
            ManageModelsDialog.setObjectName(u"ManageModelsDialog")
        ManageModelsDialog.resize(776, 403)
        ManageModelsDialog.setMinimumSize(QSize(450, 300))
        self.main_layout = QVBoxLayout(ManageModelsDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.scroll_area = QScrollArea(ManageModelsDialog)
        self.scroll_area.setObjectName(u"scroll_area")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_contents = QWidget()
        self.scroll_contents.setObjectName(u"scroll_contents")
        self.scroll_contents.setGeometry(QRect(0, 0, 750, 311))
        self.scroll_contents_layout = QVBoxLayout(self.scroll_contents)
        self.scroll_contents_layout.setObjectName(u"scroll_contents_layout")
        self.scroll_area.setWidget(self.scroll_contents)

        self.main_layout.addWidget(self.scroll_area)

        self.button_layout = QHBoxLayout()
        self.button_layout.setObjectName(u"button_layout")
        self.status_label = QLabel(ManageModelsDialog)
        self.status_label.setObjectName(u"status_label")

        self.button_layout.addWidget(self.status_label)

        self.button_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.button_layout.addItem(self.button_spacer)

        self.download_button = QPushButton(ManageModelsDialog)
        self.download_button.setObjectName(u"download_button")
        self.download_button.setEnabled(False)

        self.button_layout.addWidget(self.download_button)

        self.close_button = QPushButton(ManageModelsDialog)
        self.close_button.setObjectName(u"close_button")

        self.button_layout.addWidget(self.close_button)


        self.main_layout.addLayout(self.button_layout)


        self.retranslateUi(ManageModelsDialog)

        QMetaObject.connectSlotsByName(ManageModelsDialog)
    # setupUi

    def retranslateUi(self, ManageModelsDialog):
        ManageModelsDialog.setWindowTitle(QCoreApplication.translate("ManageModelsDialog", u"Manage Models", None))
        self.status_label.setText(QCoreApplication.translate("ManageModelsDialog", u"Loading available models...", None))
        self.download_button.setText(QCoreApplication.translate("ManageModelsDialog", u"Download All", None))
        self.close_button.setText(QCoreApplication.translate("ManageModelsDialog", u"Close", None))
    # retranslateUi

