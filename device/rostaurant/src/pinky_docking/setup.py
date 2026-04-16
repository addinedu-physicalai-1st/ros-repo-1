from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'pinky_docking'

setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py') + glob('launch/*.npz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Your Name',
    maintainer_email='you@example.com',
    description='ArUco 마커 탐지 기반 Pinky Nav2 자율주차 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'docking_node = pinky_docking.docking_node:main',
            'parking_node = pinky_docking.parking_node:main',
        ],
    },
)