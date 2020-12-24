#! /usr/bin/python3
import json
import dicttoxml
import xml.etree.ElementTree as xtree
import argparse
import re
from bs4 import BeautifulSoup
from time import time, ctime

## Build command line argument parser
cmdParse = argparse.ArgumentParser(description="Application to convert a geojson file into xml for vatSys. Tip: use https://mapshaper.org/ to simplify the file first.")
cmdParse.add_argument('-p', '--print', help='print the xml file to screen', action='store_true')
cmdParse.add_argument('-c', '--convert', help='carry out the initial geoson to xml conversion', action='store_true')
args = cmdParse.parse_args()

def convertFile(fileIn, fileOut):
    with open(fileIn, 'r') as f:
        data = json.loads(f.read())
        format = json.dumps(data, indent=2)
        xml = dicttoxml.dicttoxml(data)
        with open(fileOut, 'w') as w:
            string = str(xml)
            w.write(string)
        w.close()

if args.convert:
    convertFile('uk.json', 'UK_COASTLINE.xml')
elif args.print:
    ## Define the XML root tag
    xml = xtree.Element("Maps")
    xml.set('xmlns:xsd', 'http://www.w3.org/2001/XMLSchema')
    xml.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

    ## Set a tag for XML generation time
    xml.set('generated', ctime(time()))

    xmlMap = xtree.SubElement(xml, 'Map')
    xmlMap.set('Type', 'System')
    xmlMap.set('Name', 'UK_COASTLINE')
    xmlMap.set('Priority', '3')

    with open('UK_COASTLINE.xml', 'r') as f:
        data = f.read()

    bs_data = BeautifulSoup(data, "lxml")

    for tag in bs_data.find_all('coordinates'):
        xmlLine = xtree.SubElement(xmlMap, 'Line')
        xmlLine.set('Name', 'Coastline')
        coords = re.finditer(r'(?<=\<item type\=\"float\"\>)([\+|\-])([0-9]{1}\.[0-9]{4})([0-9]{11})(\<\/item\>\n\<item type\=\"float\"\>)([0-9]{2}\.)([0-9]{4})([0-9]{10})', str(tag))

        output = ''
        for c in coords:
            formatted = "+" + c.group(5) + c.group(6) + c.group(1) + "00" + c.group(2) + "/\n"
            output += str(formatted)

        xmlLine.text = output
    treeOut = xtree.ElementTree(xml)
    treeOut.write('Build/Maps/UK_COAST.xml', encoding="utf-8", xml_declaration=True)

else:
    print("Nothing to do here\n")
    cmdParse.print_help()
