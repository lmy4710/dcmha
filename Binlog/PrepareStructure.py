# -*- encoding: utf-8 -*-
'''
@author: Great God
'''

import sys
sys.path.append("..")
from lib.InitDB import InitMyDB
class GetStruct:
    def __init__(self,host=None,port=None,user=None,passwd=None,socket=None):
        self.connection = InitMyDB(mysql_host=host).Init()
        self.cur = self.connection.cursor()

    def GetColumn(self,*args):
        '''args顺序 database、tablename'''
        column_list = []
        column_type_list = []
        pk_idex = None

        sql = 'select COLUMN_NAME,COLUMN_KEY,COLUMN_TYPE from INFORMATION_SCHEMA.COLUMNS where table_schema=%s and table_name=%s order by ORDINAL_POSITION;'
        self.cur.execute(sql,args=args)
        result = self.cur.fetchall()
        for idex,row in enumerate(result):
            column_list.append(row['COLUMN_NAME'])
            column_type_list.append(row['COLUMN_TYPE'])
            if row['COLUMN_KEY'] == 'PRI':
                pk_idex = idex
        return column_list,pk_idex,column_type_list
        self.cur.close()
        self.connection.close()
