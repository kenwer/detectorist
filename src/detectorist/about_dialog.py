# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'about_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.10.0
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)
from . import resources_rc

class Ui_AboutDialog(object):
    def setupUi(self, AboutDialog):
        if not AboutDialog.objectName():
            AboutDialog.setObjectName(u"AboutDialog")
        AboutDialog.resize(450, 200)
        AboutDialog.setMinimumSize(QSize(450, 200))
        self.verticalLayout = QVBoxLayout(AboutDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.icon_label = QLabel(AboutDialog)
        self.icon_label.setObjectName(u"icon_label")
        self.icon_label.setMinimumSize(QSize(128, 128))
        self.icon_label.setMaximumSize(QSize(128, 128))
        self.icon_label.setPixmap(QPixmap(u":/icons/icon.png"))
        self.icon_label.setScaledContents(True)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout.addWidget(self.icon_label)

        self.textLayout = QVBoxLayout()
        self.textLayout.setObjectName(u"textLayout")
        self.app_name_label = QLabel(AboutDialog)
        self.app_name_label.setObjectName(u"app_name_label")
        font = QFont()
        font.setPointSize(34)
        font.setWeight(QFont.ExtraLight)
        font.setKerning(True)
        self.app_name_label.setFont(font)
        self.app_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.textLayout.addWidget(self.app_name_label)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.textLayout.addItem(self.verticalSpacer)

        self.version_label = QLabel(AboutDialog)
        self.version_label.setObjectName(u"version_label")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.textLayout.addWidget(self.version_label)

        self.author_label = QLabel(AboutDialog)
        self.author_label.setObjectName(u"author_label")
        self.author_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.textLayout.addWidget(self.author_label)

        self.link_label = QLabel(AboutDialog)
        self.link_label.setObjectName(u"link_label")
        self.link_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.link_label.setOpenExternalLinks(True)

        self.textLayout.addWidget(self.link_label)


        self.horizontalLayout.addLayout(self.textLayout)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.button_box = QDialogButtonBox(AboutDialog)
        self.button_box.setObjectName(u"button_box")
        self.button_box.setOrientation(Qt.Orientation.Horizontal)
        self.button_box.setStandardButtons(QDialogButtonBox.StandardButton.Ok)

        self.verticalLayout.addWidget(self.button_box)


        self.retranslateUi(AboutDialog)
        self.button_box.accepted.connect(AboutDialog.accept)
        self.button_box.rejected.connect(AboutDialog.reject)

        QMetaObject.connectSlotsByName(AboutDialog)
    # setupUi

    def retranslateUi(self, AboutDialog):
        AboutDialog.setWindowTitle(QCoreApplication.translate("AboutDialog", u"About Detectorist", None))
        self.icon_label.setText("")
        self.app_name_label.setText(QCoreApplication.translate("AboutDialog", u"Detectorist", None))
        self.version_label.setText(QCoreApplication.translate("AboutDialog", u"Version: ", None))
        self.author_label.setText(QCoreApplication.translate("AboutDialog", u"Author: Ken Werner", None))
        self.link_label.setText(QCoreApplication.translate("AboutDialog", u"<a href=\"https://github.com/kenwer/detectorist\">https://github.com/kenwer/detectorist</a>", None))
    # retranslateUi

