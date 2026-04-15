from setuptools import find_packages, setup
import os
import glob

package_name = 'rostaurant_safety_layer'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch',
            glob.glob(os.path.join('launch', '*launch.*'))),
        ('share/' + package_name + '/config',
            glob.glob(os.path.join('config', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pl3',
    maintainer_email='kyung133851@pinklab.art',
    description='Safety layer node that filters velocity commands for Rost Pro.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'safety_layer_node=rostaurant_safety_layer.safety_layer_node:main',
            'child_detection_node=rostaurant_safety_layer.child_detection_node:main',
            'event_recorder_node=rostaurant_safety_layer.event_recorder_node:main',
            'buzzer_node=rostaurant_safety_layer.buzzer_node:main',
            'fake_scan_node=rostaurant_safety_layer.fake_scan_node:main',
        ],
    },
)
