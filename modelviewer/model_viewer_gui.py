# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'model_viewer_gui.ui'
##
## Created by: Qt User Interface Compiler version 6.9.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QListView,
    QMainWindow, QMenu, QMenuBar, QRadioButton,
    QScrollArea, QSizePolicy, QSlider, QSpacerItem,
    QSpinBox, QSplitter, QStatusBar, QVBoxLayout,
    QWidget)

class Ui_ModelViewerUI(object):
    def setupUi(self, ModelViewerUI):
        if not ModelViewerUI.objectName():
            ModelViewerUI.setObjectName(u"ModelViewerUI")
        ModelViewerUI.resize(1500, 750)
        self.openFolderAction = QAction(ModelViewerUI)
        self.openFolderAction.setObjectName(u"openFolderAction")
        self.cropAction = QAction(ModelViewerUI)
        self.cropAction.setObjectName(u"cropAction")
        self.detectFishAction = QAction(ModelViewerUI)
        self.detectFishAction.setObjectName(u"detectFishAction")
        self.actionCropSaveImage = QAction(ModelViewerUI)
        self.actionCropSaveImage.setObjectName(u"actionCropSaveImage")
        self.actionCropSaveImage.setEnabled(False)
        self.actionCropSaveAllImages = QAction(ModelViewerUI)
        self.actionCropSaveAllImages.setObjectName(u"actionCropSaveAllImages")
        self.actionCropSaveAllImages.setEnabled(False)
        self.actionAbout = QAction(ModelViewerUI)
        self.actionAbout.setObjectName(u"actionAbout")
        self.centralWidget = QWidget(ModelViewerUI)
        self.centralWidget.setObjectName(u"centralWidget")
        self.mainLayout = QHBoxLayout(self.centralWidget)
        self.mainLayout.setObjectName(u"mainLayout")
        self.splitter = QSplitter(self.centralWidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.imageListView = QListView(self.splitter)
        self.imageListView.setObjectName(u"imageListView")
        self.splitter.addWidget(self.imageListView)
        self.imageLabel = QLabel(self.splitter)
        self.imageLabel.setObjectName(u"imageLabel")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(2)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.imageLabel.sizePolicy().hasHeightForWidth())
        self.imageLabel.setSizePolicy(sizePolicy)
        self.imageLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.splitter.addWidget(self.imageLabel)
        self.rightSidewidget = QWidget(self.splitter)
        self.rightSidewidget.setObjectName(u"rightSidewidget")
        self.verticalLayout = QVBoxLayout(self.rightSidewidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.modelGroupBox = QGroupBox(self.rightSidewidget)
        self.modelGroupBox.setObjectName(u"modelGroupBox")
        self.modelGroupBox.setEnabled(True)
        self.gridLayout_2 = QGridLayout(self.modelGroupBox)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.modelSelectComboBox = QComboBox(self.modelGroupBox)
        self.modelSelectComboBox.setObjectName(u"modelSelectComboBox")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.modelSelectComboBox.sizePolicy().hasHeightForWidth())
        self.modelSelectComboBox.setSizePolicy(sizePolicy1)

        self.gridLayout_2.addWidget(self.modelSelectComboBox, 0, 0, 1, 3)

        self.confidenceLabel = QLabel(self.modelGroupBox)
        self.confidenceLabel.setObjectName(u"confidenceLabel")

        self.gridLayout_2.addWidget(self.confidenceLabel, 1, 0, 1, 1)

        self.confidenceSlider = QSlider(self.modelGroupBox)
        self.confidenceSlider.setObjectName(u"confidenceSlider")
        self.confidenceSlider.setEnabled(True)
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(1)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.confidenceSlider.sizePolicy().hasHeightForWidth())
        self.confidenceSlider.setSizePolicy(sizePolicy2)
        self.confidenceSlider.setMaximum(100)
        self.confidenceSlider.setSingleStep(10)
        self.confidenceSlider.setSliderPosition(75)
        self.confidenceSlider.setOrientation(Qt.Orientation.Horizontal)
        self.confidenceSlider.setTickPosition(QSlider.TickPosition.NoTicks)

        self.gridLayout_2.addWidget(self.confidenceSlider, 1, 1, 1, 1)

        self.confidenceSpinBox = QSpinBox(self.modelGroupBox)
        self.confidenceSpinBox.setObjectName(u"confidenceSpinBox")
        self.confidenceSpinBox.setMaximum(100)
        self.confidenceSpinBox.setValue(75)

        self.gridLayout_2.addWidget(self.confidenceSpinBox, 1, 2, 1, 1)

        self.nmsLabel = QLabel(self.modelGroupBox)
        self.nmsLabel.setObjectName(u"nmsLabel")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.nmsLabel.sizePolicy().hasHeightForWidth())
        self.nmsLabel.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.nmsLabel, 2, 0, 1, 1)

        self.nmsSlider = QSlider(self.modelGroupBox)
        self.nmsSlider.setObjectName(u"nmsSlider")
        self.nmsSlider.setEnabled(True)
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.nmsSlider.sizePolicy().hasHeightForWidth())
        self.nmsSlider.setSizePolicy(sizePolicy4)
        self.nmsSlider.setMaximum(100)
        self.nmsSlider.setSingleStep(10)
        self.nmsSlider.setValue(45)
        self.nmsSlider.setSliderPosition(45)
        self.nmsSlider.setOrientation(Qt.Orientation.Horizontal)
        self.nmsSlider.setTickPosition(QSlider.TickPosition.NoTicks)

        self.gridLayout_2.addWidget(self.nmsSlider, 2, 1, 1, 1)

        self.nmsSpinBox = QSpinBox(self.modelGroupBox)
        self.nmsSpinBox.setObjectName(u"nmsSpinBox")
        self.nmsSpinBox.setMaximum(100)
        self.nmsSpinBox.setValue(45)

        self.gridLayout_2.addWidget(self.nmsSpinBox, 2, 2, 1, 1)


        self.verticalLayout.addWidget(self.modelGroupBox)

        self.detectionInfoGroupBox = QGroupBox(self.rightSidewidget)
        self.detectionInfoGroupBox.setObjectName(u"detectionInfoGroupBox")
        self.verticalLayout_4 = QVBoxLayout(self.detectionInfoGroupBox)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.detectionInfoLabel = QLabel(self.detectionInfoGroupBox)
        self.detectionInfoLabel.setObjectName(u"detectionInfoLabel")

        self.verticalLayout_4.addWidget(self.detectionInfoLabel)


        self.verticalLayout.addWidget(self.detectionInfoGroupBox)

        self.cropInfoGroupBox = QGroupBox(self.rightSidewidget)
        self.cropInfoGroupBox.setObjectName(u"cropInfoGroupBox")
        self.grdlyt_crop = QGridLayout(self.cropInfoGroupBox)
        self.grdlyt_crop.setObjectName(u"grdlyt_crop")
        self.cropRatioComboBox = QComboBox(self.cropInfoGroupBox)
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.setObjectName(u"cropRatioComboBox")

        self.grdlyt_crop.addWidget(self.cropRatioComboBox, 0, 0, 1, 3)

        self.paddingLabel = QLabel(self.cropInfoGroupBox)
        self.paddingLabel.setObjectName(u"paddingLabel")

        self.grdlyt_crop.addWidget(self.paddingLabel, 1, 0, 1, 1)

        self.paddingSlider = QSlider(self.cropInfoGroupBox)
        self.paddingSlider.setObjectName(u"paddingSlider")
        self.paddingSlider.setEnabled(True)
        sizePolicy2.setHeightForWidth(self.paddingSlider.sizePolicy().hasHeightForWidth())
        self.paddingSlider.setSizePolicy(sizePolicy2)
        self.paddingSlider.setMaximum(50)
        self.paddingSlider.setSingleStep(1)
        self.paddingSlider.setSliderPosition(15)
        self.paddingSlider.setOrientation(Qt.Orientation.Horizontal)
        self.paddingSlider.setTickPosition(QSlider.TickPosition.NoTicks)

        self.grdlyt_crop.addWidget(self.paddingSlider, 1, 1, 1, 1)

        self.paddingSpinBox = QSpinBox(self.cropInfoGroupBox)
        self.paddingSpinBox.setObjectName(u"paddingSpinBox")
        self.paddingSpinBox.setMaximum(50)
        self.paddingSpinBox.setValue(15)

        self.grdlyt_crop.addWidget(self.paddingSpinBox, 1, 2, 1, 1)

        self.rb_crop_to_top_conf = QRadioButton(self.cropInfoGroupBox)
        self.btngroup_crop = QButtonGroup(ModelViewerUI)
        self.btngroup_crop.setObjectName(u"btngroup_crop")
        self.btngroup_crop.addButton(self.rb_crop_to_top_conf)
        self.rb_crop_to_top_conf.setObjectName(u"rb_crop_to_top_conf")
        self.rb_crop_to_top_conf.setChecked(True)

        self.grdlyt_crop.addWidget(self.rb_crop_to_top_conf, 2, 0, 1, 2)

        self.rb_crop_largest_area = QRadioButton(self.cropInfoGroupBox)
        self.btngroup_crop.addButton(self.rb_crop_largest_area)
        self.rb_crop_largest_area.setObjectName(u"rb_crop_largest_area")
        self.rb_crop_largest_area.setChecked(False)

        self.grdlyt_crop.addWidget(self.rb_crop_largest_area, 3, 0, 1, 2)


        self.verticalLayout.addWidget(self.cropInfoGroupBox)

        self.imageInfoGroupBox = QGroupBox(self.rightSidewidget)
        self.imageInfoGroupBox.setObjectName(u"imageInfoGroupBox")
        self.verticalLayout_3 = QVBoxLayout(self.imageInfoGroupBox)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.imageInfoLabel = QLabel(self.imageInfoGroupBox)
        self.imageInfoLabel.setObjectName(u"imageInfoLabel")

        self.verticalLayout_3.addWidget(self.imageInfoLabel)


        self.verticalLayout.addWidget(self.imageInfoGroupBox)

        self.imageExifGroupBox = QGroupBox(self.rightSidewidget)
        self.imageExifGroupBox.setObjectName(u"imageExifGroupBox")
        self.horizontalLayout_2 = QHBoxLayout(self.imageExifGroupBox)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.scrollArea = QScrollArea(self.imageExifGroupBox)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents_2 = QWidget()
        self.scrollAreaWidgetContents_2.setObjectName(u"scrollAreaWidgetContents_2")
        self.scrollAreaWidgetContents_2.setGeometry(QRect(0, 0, 254, 72))
        self.horizontalLayout = QHBoxLayout(self.scrollAreaWidgetContents_2)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.imageExifLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.imageExifLabel.setObjectName(u"imageExifLabel")

        self.horizontalLayout.addWidget(self.imageExifLabel)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents_2)

        self.horizontalLayout_2.addWidget(self.scrollArea)


        self.verticalLayout.addWidget(self.imageExifGroupBox)

        self.rightSideVerticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.rightSideVerticalSpacer)

        self.splitter.addWidget(self.rightSidewidget)

        self.mainLayout.addWidget(self.splitter)

        ModelViewerUI.setCentralWidget(self.centralWidget)
        self.menuBar = QMenuBar(ModelViewerUI)
        self.menuBar.setObjectName(u"menuBar")
        self.menuBar.setGeometry(QRect(0, 0, 1500, 24))
        self.menuFile = QMenu(self.menuBar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuTools = QMenu(self.menuBar)
        self.menuTools.setObjectName(u"menuTools")
        self.menuHelp = QMenu(self.menuBar)
        self.menuHelp.setObjectName(u"menuHelp")
        ModelViewerUI.setMenuBar(self.menuBar)
        self.statusBar = QStatusBar(ModelViewerUI)
        self.statusBar.setObjectName(u"statusBar")
        ModelViewerUI.setStatusBar(self.statusBar)

        self.menuBar.addAction(self.menuFile.menuAction())
        self.menuBar.addAction(self.menuTools.menuAction())
        self.menuBar.addAction(self.menuHelp.menuAction())
        self.menuFile.addAction(self.openFolderAction)
        self.menuTools.addAction(self.actionCropSaveImage)
        self.menuTools.addAction(self.actionCropSaveAllImages)
        self.menuHelp.addAction(self.actionAbout)

        self.retranslateUi(ModelViewerUI)
        self.confidenceSpinBox.valueChanged.connect(self.confidenceSlider.setValue)
        self.nmsSpinBox.valueChanged.connect(self.nmsSlider.setValue)
        self.confidenceSlider.valueChanged.connect(self.confidenceSpinBox.setValue)
        self.nmsSlider.valueChanged.connect(self.nmsSpinBox.setValue)
        self.paddingSlider.valueChanged.connect(self.paddingSpinBox.setValue)
        self.paddingSpinBox.valueChanged.connect(self.paddingSlider.setValue)

        QMetaObject.connectSlotsByName(ModelViewerUI)
    # setupUi

    def retranslateUi(self, ModelViewerUI):
        ModelViewerUI.setWindowTitle(QCoreApplication.translate("ModelViewerUI", u"Fish Model Viewer", None))
        self.openFolderAction.setText(QCoreApplication.translate("ModelViewerUI", u"Open Folder...", None))
#if QT_CONFIG(shortcut)
        self.openFolderAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+O", None))
#endif // QT_CONFIG(shortcut)
        self.cropAction.setText(QCoreApplication.translate("ModelViewerUI", u"Crop to Selection", None))
#if QT_CONFIG(shortcut)
        self.cropAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+S", None))
#endif // QT_CONFIG(shortcut)
        self.detectFishAction.setText(QCoreApplication.translate("ModelViewerUI", u"Detect Fish (AI)", None))
#if QT_CONFIG(shortcut)
        self.detectFishAction.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+D", None))
#endif // QT_CONFIG(shortcut)
        self.actionCropSaveImage.setText(QCoreApplication.translate("ModelViewerUI", u"Crop && copy image", None))
        self.actionCropSaveAllImages.setText(QCoreApplication.translate("ModelViewerUI", u"Crop && copy all images", None))
#if QT_CONFIG(shortcut)
        self.actionCropSaveAllImages.setShortcut(QCoreApplication.translate("ModelViewerUI", u"Ctrl+K", None))
#endif // QT_CONFIG(shortcut)
        self.actionAbout.setText(QCoreApplication.translate("ModelViewerUI", u"About", None))
        self.imageLabel.setStyleSheet(QCoreApplication.translate("ModelViewerUI", u"background-color: gray;", None))
        self.imageLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Open Folder...", None))
        self.modelGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Model", None))
#if QT_CONFIG(tooltip)
        self.confidenceLabel.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The confidence threshold for filtering detections", None))
#endif // QT_CONFIG(tooltip)
        self.confidenceLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Confidence", None))
#if QT_CONFIG(tooltip)
        self.confidenceSlider.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The confidence threshold for filtering detections", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.nmsLabel.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The Non-Maximum Suppression threshold for the bounding boxes", None))
#endif // QT_CONFIG(tooltip)
        self.nmsLabel.setText(QCoreApplication.translate("ModelViewerUI", u"NMS", None))
#if QT_CONFIG(tooltip)
        self.nmsSlider.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The Non-Maximum Suppression threshold for the bounding boxes", None))
#endif // QT_CONFIG(tooltip)
        self.detectionInfoGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Detection", None))
        self.detectionInfoLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Objects			: -\n"
"Detection time		: -\n"
"Highest confidence	: -", None))
        self.cropInfoGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Crop", None))
        self.cropRatioComboBox.setItemText(0, QCoreApplication.translate("ModelViewerUI", u"3:2", None))
        self.cropRatioComboBox.setItemText(1, QCoreApplication.translate("ModelViewerUI", u"4:3", None))
        self.cropRatioComboBox.setItemText(2, QCoreApplication.translate("ModelViewerUI", u"16:9", None))

#if QT_CONFIG(tooltip)
        self.paddingLabel.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The padding added to the crop (percent of the image size in percent)", None))
#endif // QT_CONFIG(tooltip)
        self.paddingLabel.setText(QCoreApplication.translate("ModelViewerUI", u"Padding", None))
#if QT_CONFIG(tooltip)
        self.paddingSlider.setToolTip(QCoreApplication.translate("ModelViewerUI", u"The padding added to the crop (percent of the image size in percent)", None))
#endif // QT_CONFIG(tooltip)
        self.rb_crop_to_top_conf.setText(QCoreApplication.translate("ModelViewerUI", u"Crop to highest confidence box", None))
        self.rb_crop_largest_area.setText(QCoreApplication.translate("ModelViewerUI", u"Crop to largest area", None))
        self.imageInfoGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Image", None))
        self.imageInfoLabel.setText(QCoreApplication.translate("ModelViewerUI", u"-", None))
        self.imageExifGroupBox.setTitle(QCoreApplication.translate("ModelViewerUI", u"Exif", None))
        self.menuFile.setTitle(QCoreApplication.translate("ModelViewerUI", u"File", None))
        self.menuTools.setTitle(QCoreApplication.translate("ModelViewerUI", u"Tools", None))
        self.menuHelp.setTitle(QCoreApplication.translate("ModelViewerUI", u"Help", None))
    # retranslateUi

