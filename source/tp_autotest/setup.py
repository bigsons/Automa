from setuptools import setup, find_packages

setup(
    name='tp_autotest',
    version='0.1.1',
    description='A Python package for extending Airtest with Selenium and other utilities.',
    author='pengshaojie',
    author_email='pengshaojie@tp-link.com.hk',
    packages=find_packages(),
    install_requires=[
        "airtest",
        'selenium',
        'pynput',
        'opencv-python',
        'pywifi',
        'psutil',
        'pyserial',
        'jinja2',
        "six",
        "paddlepaddle",
        "paddleocr",
        "numpy ",
        "websockets",
        "iperf3",
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Testing',
        'License :: OSI Approved :: Apache License 2.0',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    python_requires='>=3.6',
    entry_points={
        'console_scripts': [
            'autotest-server = tp_autotest.server:main',
        ],
    },
    include_package_data=True,
    package_data={
        'tp_autotest': [
            "page/**/*",
            "page/**/**/*",
            "page/**/**/**/*",
            "page/**/**/**/**/*"
        ],
    },
)