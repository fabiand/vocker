from setuptools import setup


setup(name='vocker',
      version='0.0.1',
      description='',
      long_description='',
      author='Fabian Deutsch',
      author_email='fedeutsch@redhat.com',
      url='https://github.com/fabiand/vocker',
      license="GPLv3",
      py_modules=['vocker'],
      setup_requires=['pytest-runner'],
      tests_require=['pytest', 'pytest-cov'],
      entry_points="""
          [console_scripts]
              vocker=vocker:run
      """)
