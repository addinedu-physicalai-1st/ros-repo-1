import glob
import os

from setuptools import find_packages, setup

package_name = 'rost_state'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        # ament index registration
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        # package.xml
        ('share/' + package_name, ['package.xml']),
        # launch files
        (
            'share/' + package_name + '/launch',
            glob.glob(os.path.join('launch', '*launch.*')),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pl3',
    maintainer_email='kyung133851@pinklab.art',
    description='Reusable ROS2 FSM framework for robot task management.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # Main FSM node — launched by rost_state.launch.py
            'fsm_node=rost_state.fsm_node:main',
        ],
    },
)
