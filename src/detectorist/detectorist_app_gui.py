# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'detectorist_app_gui.ui'
##
## Created by: Qt User Interface Compiler version 6.10.0
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QListView, QMainWindow, QMenu,
    QMenuBar, QRadioButton, QScrollArea, QSizePolicy,
    QSlider, QSpinBox, QSplitter, QStatusBar,
    QVBoxLayout, QWidget)

class Ui_DetectoristAppUI(object):
    def setupUi(self, DetectoristAppUI):
        if not DetectoristAppUI.objectName():
            DetectoristAppUI.setObjectName(u"DetectoristAppUI")
        DetectoristAppUI.resize(1500, 750)
        self.openImagesAction = QAction(DetectoristAppUI)
        self.openImagesAction.setObjectName(u"openImagesAction")
        self.openFolderAction = QAction(DetectoristAppUI)
        self.openFolderAction.setObjectName(u"openFolderAction")
        self.actionCropSaveImage = QAction(DetectoristAppUI)
        self.actionCropSaveImage.setObjectName(u"actionCropSaveImage")
        self.actionCropSaveImage.setEnabled(False)
        self.actionCropSaveSelectedImages = QAction(DetectoristAppUI)
        self.actionCropSaveSelectedImages.setObjectName(u"actionCropSaveSelectedImages")
        self.actionCropSaveSelectedImages.setEnabled(False)
        self.actionCropSaveAllImages = QAction(DetectoristAppUI)
        self.actionCropSaveAllImages.setObjectName(u"actionCropSaveAllImages")
        self.actionCropSaveAllImages.setEnabled(False)
        self.actionAbout = QAction(DetectoristAppUI)
        self.actionAbout.setObjectName(u"actionAbout")
        self.actionSort_images_by_object_class = QAction(DetectoristAppUI)
        self.actionSort_images_by_object_class.setObjectName(u"actionSort_images_by_object_class")
        self.actionSort_images_by_object_class.setEnabled(False)
        self.centralWidget = QWidget(DetectoristAppUI)
        self.centralWidget.setObjectName(u"centralWidget")
        self.mainLayout = QHBoxLayout(self.centralWidget)
        self.mainLayout.setObjectName(u"mainLayout")
        self.splitter = QSplitter(self.centralWidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.imageListView = QListView(self.splitter)
        self.imageListView.setObjectName(u"imageListView")
        self.imageListView.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.imageListView.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        self.confidenceSlider.setMinimum(1)
        self.confidenceSlider.setMaximum(100)
        self.confidenceSlider.setSingleStep(10)
        self.confidenceSlider.setSliderPosition(75)
        self.confidenceSlider.setOrientation(Qt.Orientation.Horizontal)
        self.confidenceSlider.setTickPosition(QSlider.TickPosition.NoTicks)

        self.gridLayout_2.addWidget(self.confidenceSlider, 1, 1, 1, 1)

        self.confidenceSpinBox = QSpinBox(self.modelGroupBox)
        self.confidenceSpinBox.setObjectName(u"confidenceSpinBox")
        self.confidenceSpinBox.setMinimum(1)
        self.confidenceSpinBox.setMaximum(100)
        self.confidenceSpinBox.setValue(75)

        self.gridLayout_2.addWidget(self.confidenceSpinBox, 1, 2, 1, 1)


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
        self.rb_crop_all_detected_objects = QRadioButton(self.cropInfoGroupBox)
        self.btngroup_crop = QButtonGroup(DetectoristAppUI)
        self.btngroup_crop.setObjectName(u"btngroup_crop")
        self.btngroup_crop.addButton(self.rb_crop_all_detected_objects)
        self.rb_crop_all_detected_objects.setObjectName(u"rb_crop_all_detected_objects")
        self.rb_crop_all_detected_objects.setChecked(True)

        self.grdlyt_crop.addWidget(self.rb_crop_all_detected_objects, 0, 0, 1, 2)

        self.rb_crop_to_top_conf = QRadioButton(self.cropInfoGroupBox)
        self.btngroup_crop.addButton(self.rb_crop_to_top_conf)
        self.rb_crop_to_top_conf.setObjectName(u"rb_crop_to_top_conf")
        self.rb_crop_to_top_conf.setChecked(False)

        self.grdlyt_crop.addWidget(self.rb_crop_to_top_conf, 1, 0, 1, 2)

        self.rb_crop_largest_area = QRadioButton(self.cropInfoGroupBox)
        self.btngroup_crop.addButton(self.rb_crop_largest_area)
        self.rb_crop_largest_area.setObjectName(u"rb_crop_largest_area")
        self.rb_crop_largest_area.setChecked(False)

        self.grdlyt_crop.addWidget(self.rb_crop_largest_area, 2, 0, 1, 2)

        self.cropRatioComboBox = QComboBox(self.cropInfoGroupBox)
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.addItem("")
        self.cropRatioComboBox.setObjectName(u"cropRatioComboBox")

        self.grdlyt_crop.addWidget(self.cropRatioComboBox, 3, 0, 1, 3)

        self.paddingLabel = QLabel(self.cropInfoGroupBox)
        self.paddingLabel.setObjectName(u"paddingLabel")

        self.grdlyt_crop.addWidget(self.paddingLabel, 4, 0, 1, 1)

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

        self.grdlyt_crop.addWidget(self.paddingSlider, 4, 1, 1, 1)

        self.paddingSpinBox = QSpinBox(self.cropInfoGroupBox)
        self.paddingSpinBox.setObjectName(u"paddingSpinBox")
        self.paddingSpinBox.setMaximum(50)
        self.paddingSpinBox.setValue(15)

        self.grdlyt_crop.addWidget(self.paddingSpinBox, 4, 2, 1, 1)

        self.cb_comp_cam_exposure = QCheckBox(self.cropInfoGroupBox)
        self.cb_comp_cam_exposure.setObjectName(u"cb_comp_cam_exposure")
        self.cb_comp_cam_exposure.setChecked(True)

        self.grdlyt_crop.addWidget(self.cb_comp_cam_exposure, 5, 0, 1, 3)


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
        self.horizontalLayout = QHBoxLayout(self.imageExifGroupBox)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.scrollArea = QScrollArea(self.imageExifGroupBox)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 298, 138))
        self.horizontalLayout_2 = QHBoxLayout(self.scrollAreaWidgetContents)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.imageExifLabel = QLabel(self.scrollAreaWidgetContents)
        self.imageExifLabel.setObjectName(u"imageExifLabel")
        self.imageExifLabel.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse|Qt.TextInteractionFlag.TextSelectableByMouse)

        self.horizontalLayout_2.addWidget(self.imageExifLabel, 0, Qt.AlignmentFlag.AlignTop)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents)

        self.horizontalLayout.addWidget(self.scrollArea)


        self.verticalLayout.addWidget(self.imageExifGroupBox)

        self.splitter.addWidget(self.rightSidewidget)

        self.mainLayout.addWidget(self.splitter)

        DetectoristAppUI.setCentralWidget(self.centralWidget)
        self.menuBar = QMenuBar(DetectoristAppUI)
        self.menuBar.setObjectName(u"menuBar")
        self.menuBar.setGeometry(QRect(0, 0, 1500, 30))
        self.menuFile = QMenu(self.menuBar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuActions = QMenu(self.menuBar)
        self.menuActions.setObjectName(u"menuActions")
        self.menuHelp = QMenu(self.menuBar)
        self.menuHelp.setObjectName(u"menuHelp")
        DetectoristAppUI.setMenuBar(self.menuBar)
        self.statusBar = QStatusBar(DetectoristAppUI)
        self.statusBar.setObjectName(u"statusBar")
        DetectoristAppUI.setStatusBar(self.statusBar)

        self.menuBar.addAction(self.menuFile.menuAction())
        self.menuBar.addAction(self.menuActions.menuAction())
        self.menuBar.addAction(self.menuHelp.menuAction())
        self.menuFile.addAction(self.openImagesAction)
        self.menuFile.addAction(self.openFolderAction)
        self.menuActions.addAction(self.actionSort_images_by_object_class)
        self.menuActions.addSeparator()
        self.menuActions.addAction(self.actionCropSaveImage)
        self.menuActions.addAction(self.actionCropSaveSelectedImages)
        self.menuActions.addAction(self.actionCropSaveAllImages)
        self.menuHelp.addAction(self.actionAbout)

        self.retranslateUi(DetectoristAppUI)
        self.confidenceSpinBox.valueChanged.connect(self.confidenceSlider.setValue)
        self.confidenceSlider.valueChanged.connect(self.confidenceSpinBox.setValue)
        self.paddingSlider.valueChanged.connect(self.paddingSpinBox.setValue)
        self.paddingSpinBox.valueChanged.connect(self.paddingSlider.setValue)

        QMetaObject.connectSlotsByName(DetectoristAppUI)
    # setupUi

    def retranslateUi(self, DetectoristAppUI):
        DetectoristAppUI.setWindowTitle(QCoreApplication.translate("DetectoristAppUI", u"Detectorist", None))
        self.openImagesAction.setText(QCoreApplication.translate("DetectoristAppUI", u"Open Image(s)...", None))
#if QT_CONFIG(shortcut)
        self.openImagesAction.setShortcut(QCoreApplication.translate("DetectoristAppUI", u"Ctrl+O", None))
#endif // QT_CONFIG(shortcut)
        self.openFolderAction.setText(QCoreApplication.translate("DetectoristAppUI", u"Open Folder...", None))
#if QT_CONFIG(shortcut)
        self.openFolderAction.setShortcut(QCoreApplication.translate("DetectoristAppUI", u"Ctrl+Shift+O", None))
#endif // QT_CONFIG(shortcut)
        self.actionCropSaveImage.setText(QCoreApplication.translate("DetectoristAppUI", u"Crop && copy current image", None))
        self.actionCropSaveSelectedImages.setText(QCoreApplication.translate("DetectoristAppUI", u"Crop && copy selected images", None))
        self.actionCropSaveAllImages.setText(QCoreApplication.translate("DetectoristAppUI", u"Crop && copy all images", None))
#if QT_CONFIG(shortcut)
        self.actionCropSaveAllImages.setShortcut(QCoreApplication.translate("DetectoristAppUI", u"Ctrl+K", None))
#endif // QT_CONFIG(shortcut)
        self.actionAbout.setText(QCoreApplication.translate("DetectoristAppUI", u"About", None))
        self.actionSort_images_by_object_class.setText(QCoreApplication.translate("DetectoristAppUI", u"Sort images into folders (by deteced object class)", None))
#if QT_CONFIG(shortcut)
        self.actionSort_images_by_object_class.setShortcut(QCoreApplication.translate("DetectoristAppUI", u"Ctrl+Shift+S", None))
#endif // QT_CONFIG(shortcut)
        self.imageLabel.setStyleSheet(QCoreApplication.translate("DetectoristAppUI", u"background-color: gray;", None))
        self.imageLabel.setText(QCoreApplication.translate("DetectoristAppUI", u"Open Folder...", None))
        self.modelGroupBox.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Model", None))
#if QT_CONFIG(tooltip)
        self.modelSelectComboBox.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"Model used for object detection", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.confidenceLabel.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"The confidence threshold for filtering detections", None))
#endif // QT_CONFIG(tooltip)
        self.confidenceLabel.setText(QCoreApplication.translate("DetectoristAppUI", u"Confidence", None))
#if QT_CONFIG(tooltip)
        self.confidenceSlider.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"The confidence threshold for filtering detections", None))
#endif // QT_CONFIG(tooltip)
        self.detectionInfoGroupBox.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Detection", None))
        self.detectionInfoLabel.setText(QCoreApplication.translate("DetectoristAppUI", u"Objects			: -\n"
"Detection time		: -\n"
"Highest confidence	: -", None))
        self.cropInfoGroupBox.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Crop", None))
#if QT_CONFIG(tooltip)
        self.rb_crop_all_detected_objects.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"Crops all detected objects into individual images", None))
#endif // QT_CONFIG(tooltip)
        self.rb_crop_all_detected_objects.setText(QCoreApplication.translate("DetectoristAppUI", u"Crop all detected objects", None))
#if QT_CONFIG(tooltip)
        self.rb_crop_to_top_conf.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"Crops the object with the highest confidence into a new image", None))
#endif // QT_CONFIG(tooltip)
        self.rb_crop_to_top_conf.setText(QCoreApplication.translate("DetectoristAppUI", u"Crop to object with highest confidence", None))
#if QT_CONFIG(tooltip)
        self.rb_crop_largest_area.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"Crops all detected object into a single image", None))
#endif // QT_CONFIG(tooltip)
        self.rb_crop_largest_area.setText(QCoreApplication.translate("DetectoristAppUI", u"Crop to largest area", None))
        self.cropRatioComboBox.setItemText(0, QCoreApplication.translate("DetectoristAppUI", u"aspect ratio: same as source image", None))
        self.cropRatioComboBox.setItemText(1, QCoreApplication.translate("DetectoristAppUI", u"3:2 (landscape)", None))
        self.cropRatioComboBox.setItemText(2, QCoreApplication.translate("DetectoristAppUI", u"4:3  (landscape)", None))
        self.cropRatioComboBox.setItemText(3, QCoreApplication.translate("DetectoristAppUI", u"5:4 (landscape)", None))
        self.cropRatioComboBox.setItemText(4, QCoreApplication.translate("DetectoristAppUI", u"16:9  (landscape)", None))
        self.cropRatioComboBox.setItemText(5, QCoreApplication.translate("DetectoristAppUI", u"21:9 (landscape)", None))
        self.cropRatioComboBox.setItemText(6, QCoreApplication.translate("DetectoristAppUI", u"1:1", None))
        self.cropRatioComboBox.setItemText(7, QCoreApplication.translate("DetectoristAppUI", u"2:3 (portrait)", None))
        self.cropRatioComboBox.setItemText(8, QCoreApplication.translate("DetectoristAppUI", u"3:4 (portrait)", None))
        self.cropRatioComboBox.setItemText(9, QCoreApplication.translate("DetectoristAppUI", u"4:5 (portrait)", None))
        self.cropRatioComboBox.setItemText(10, QCoreApplication.translate("DetectoristAppUI", u"9:16 (portrait)", None))
        self.cropRatioComboBox.setItemText(11, QCoreApplication.translate("DetectoristAppUI", u"9:21 (portrait)", None))

#if QT_CONFIG(tooltip)
        self.cropRatioComboBox.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"Aspect ratio for the crop", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.paddingLabel.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"The padding added to the crop (percent of the image size in percent)", None))
#endif // QT_CONFIG(tooltip)
        self.paddingLabel.setText(QCoreApplication.translate("DetectoristAppUI", u"Padding", None))
#if QT_CONFIG(tooltip)
        self.paddingSlider.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"The padding added to the crop (percent of the image size in percent)", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.cb_comp_cam_exposure.setToolTip(QCoreApplication.translate("DetectoristAppUI", u"Adjust the EV to correct for any exposure bias based on EXIF data", None))
#endif // QT_CONFIG(tooltip)
        self.cb_comp_cam_exposure.setText(QCoreApplication.translate("DetectoristAppUI", u"Auto correct camera exposure bias", None))
        self.imageInfoGroupBox.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Image", None))
        self.imageInfoLabel.setText(QCoreApplication.translate("DetectoristAppUI", u"-", None))
        self.imageExifGroupBox.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Exif", None))
        self.menuFile.setTitle(QCoreApplication.translate("DetectoristAppUI", u"File", None))
        self.menuActions.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Actions", None))
        self.menuHelp.setTitle(QCoreApplication.translate("DetectoristAppUI", u"Help", None))
    # retranslateUi

