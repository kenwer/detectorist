# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'about_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.9.2
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
import resources_rc

class Ui_AboutDialog(object):
    def setupUi(self, AboutDialog):
        if not AboutDialog.objectName():
            AboutDialog.setObjectName(u"AboutDialog")
        AboutDialog.resize(400, 200)
        AboutDialog.setMinimumSize(QSize(400, 200))
        AboutDialog.setMaximumSize(QSize(400, 200))
        self.verticalLayout = QVBoxLayout(AboutDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.iconLabel = QLabel(AboutDialog)
        self.iconLabel.setObjectName(u"iconLabel")
        self.iconLabel.setMinimumSize(QSize(128, 128))
        self.iconLabel.setMaximumSize(QSize(128, 128))
        self.iconLabel.setPixmap(QPixmap(u":/icons/icon.png"))
        self.iconLabel.setScaledContents(True)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout.addWidget(self.iconLabel)

        self.textLayout = QVBoxLayout()
        self.textLayout.setObjectName(u"textLayout")
        self.appNameLabel = QLabel(AboutDialog)
        self.appNameLabel.setObjectName(u"appNameLabel")
        font = QFont()
        font.setPointSize(34)
        font.setWeight(QFont.ExtraLight)
        font.setKerning(True)
        self.appNameLabel.setFont(font)
        self.appNameLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.textLayout.addWidget(self.appNameLabel)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.textLayout.addItem(self.verticalSpacer)

        self.versionLabel = QLabel(AboutDialog)
        self.versionLabel.setObjectName(u"versionLabel")
        self.versionLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.textLayout.addWidget(self.versionLabel)

        self.authorLabel = QLabel(AboutDialog)
        self.authorLabel.setObjectName(u"authorLabel")
        self.authorLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.textLayout.addWidget(self.authorLabel)

        self.linkLabel = QLabel(AboutDialog)
        self.linkLabel.setObjectName(u"linkLabel")
        self.linkLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.linkLabel.setOpenExternalLinks(True)

        self.textLayout.addWidget(self.linkLabel)


        self.horizontalLayout.addLayout(self.textLayout)


        self.verticalLayout.addLayout(self.horizontalLayout)

        self.buttonBox = QDialogButtonBox(AboutDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Ok)

        self.verticalLayout.addWidget(self.buttonBox)


        self.retranslateUi(AboutDialog)
        self.buttonBox.accepted.connect(AboutDialog.accept)
        self.buttonBox.rejected.connect(AboutDialog.reject)

        QMetaObject.connectSlotsByName(AboutDialog)
    # setupUi

    def retranslateUi(self, AboutDialog):
        AboutDialog.setWindowTitle(QCoreApplication.translate("AboutDialog", u"About Detectorist", None))
        self.iconLabel.setText("")
        self.appNameLabel.setText(QCoreApplication.translate("AboutDialog", u"Detectorist", None))
        self.versionLabel.setText(QCoreApplication.translate("AboutDialog", u"Version: ", None))
        self.authorLabel.setText(QCoreApplication.translate("AboutDialog", u"Author: Ken Werner", None))
        self.linkLabel.setText(QCoreApplication.translate("AboutDialog", u"<a href=\"https://github.com/kenwer/detectorist\">https://github.com/kenwer/detectorist</a>", None))
    # retranslateUi

