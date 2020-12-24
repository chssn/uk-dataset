#! /usr/bin/python3
import xmltodict
import pprint
import json
import dicttoxml

with open('uk.json', 'r') as f:
    data = json.loads(f.read())
    format = json.dumps(data, indent=2)
    xml = dicttoxml.dicttoxml(data)

    with open('UK_COASTLINE.xml', 'w') as w:
        str = str(xml)
        w.write(str)

    w.close()
