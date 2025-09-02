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
    QLabel, QSizePolicy, QVBoxLayout, QWidget)

class Ui_AboutDialog(object):
    def setupUi(self, AboutDialog):
        if not AboutDialog.objectName():
            AboutDialog.setObjectName(u"AboutDialog")
        AboutDialog.resize(400, 150)
        self.verticalLayout = QVBoxLayout(AboutDialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.appNameLabel = QLabel(AboutDialog)
        self.appNameLabel.setObjectName(u"appNameLabel")
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.appNameLabel.setFont(font)
        self.appNameLabel.setAlignment(Qt.AlignCenter)

        self.verticalLayout.addWidget(self.appNameLabel)

        self.versionLabel = QLabel(AboutDialog)
        self.versionLabel.setObjectName(u"versionLabel")
        self.versionLabel.setAlignment(Qt.AlignCenter)

        self.verticalLayout.addWidget(self.versionLabel)

        self.authorLabel = QLabel(AboutDialog)
        self.authorLabel.setObjectName(u"authorLabel")
        self.authorLabel.setAlignment(Qt.AlignCenter)

        self.verticalLayout.addWidget(self.authorLabel)

        self.linkLabel = QLabel(AboutDialog)
        self.linkLabel.setObjectName(u"linkLabel")
        self.linkLabel.setAlignment(Qt.AlignCenter)
        self.linkLabel.setOpenExternalLinks(True)

        self.verticalLayout.addWidget(self.linkLabel)

        self.buttonBox = QDialogButtonBox(AboutDialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.Ok)

        self.verticalLayout.addWidget(self.buttonBox)


        self.retranslateUi(AboutDialog)
        self.buttonBox.accepted.connect(AboutDialog.accept)
        self.buttonBox.rejected.connect(AboutDialog.reject)

        QMetaObject.connectSlotsByName(AboutDialog)
    # setupUi

    def retranslateUi(self, AboutDialog):
        AboutDialog.setWindowTitle(QCoreApplication.translate("AboutDialog", u"About oCrop", None))
        self.appNameLabel.setText(QCoreApplication.translate("AboutDialog", u"oCrop", None))
        self.versionLabel.setText(QCoreApplication.translate("AboutDialog", u"Version", None))
        self.authorLabel.setText(QCoreApplication.translate("AboutDialog", u"Author: Ken Werner", None))
        self.linkLabel.setText(QCoreApplication.translate("AboutDialog", u"<a href=\"https://github.com/kenwer/ocrop\">https://github.com/kenwer/ocrop</a>", None))
    # retranslateUi

