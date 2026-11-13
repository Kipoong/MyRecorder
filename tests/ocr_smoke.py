"""Optional actual Tesseract smoke test on a synthetic English image (not Windows validation)."""
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter, QFont
from PySide6.QtWidgets import QApplication
from myrecorder.titles import ocr_title
app=QApplication([])
image=QImage(1100,180,QImage.Format_RGB32);image.fill('white')
painter=QPainter(image);painter.setPen('black');painter.setFont(QFont('DejaVu Sans',44))
painter.drawText(35,110,'Example Lecture 42');painter.end()
buffer=QBuffer();buffer.open(QIODevice.WriteOnly);assert image.save(buffer,'PNG')
title=ocr_title(bytes(buffer.data()),'eng')
assert title=='Example Lecture 42',title
print('Actual Tesseract synthetic English recognition: PASS')
