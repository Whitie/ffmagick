# -*- coding: utf-8 -*-

import os

from os.path import join, dirname

import ffmagick

from setuptools import setup


with open(join(dirname(__file__), 'README.md')) as fp:
    long_desc = fp.read()


setup(
    name='ffmagick',
    version=ffmagick.__version__,
    py_modules=['ffmagick'],
    url='https://github.com/Whitie/ffmagick',
    license='MIT',
    author='Thorsten Weimann',
    author_email='weimann.th@yahoo.com',
    description='Build slideshows from image directories as MKV files.',
    long_description=long_desc,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Topic :: Multimedia :: Graphics :: Presentation',
    ],
    entry_points={
        'console_scripts': [
            'ffmagick = ffmagick:main',
        ],
    },
)

print(
    '',
    '***********************************************************************',
    '* Please install ffmpeg, ImageMagick and mkvtoolnix on your system    *',
    '***********************************************************************',
    sep=os.linesep, end=2 * os.linesep
)
