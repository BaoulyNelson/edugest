"""Configuration du projet EduGest.

PyMySQL est déclaré comme pilote MySQL pour Django (en remplacement de mysqlclient).
"""
import pymysql

pymysql.install_as_MySQLdb()
