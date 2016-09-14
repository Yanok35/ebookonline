# create a virtual environment
virtualenv ebookonline
cd ebookonline
source bin/activate

# install dependencies
# note fix the release version of dependencies
sudo apt-get install libjpeg-dev
sudo apt-get install libmagickwand-dev
pip install flask
pip install Pillow
pip install PyPDF2
pip install wand

# clone repository
git clone this_repository git

# launch the server
cd git/
# ./server.py
FLASK_APP=server.py flask run --host=0.0.0.0

# Cours
https://openclassrooms.com/courses/creez-vos-applications-web-avec-flask/requetes-et-reponses
