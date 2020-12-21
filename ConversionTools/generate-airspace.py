#! /usr/bin/python3
import sys
import requests
import re
import prettierfier as pretty
import xml.etree.ElementTree as xtree
import urllib3
from bs4 import BeautifulSoup
from colorama import Fore, Back, Style
from time import time, ctime
from alive_progress import alive_bar

### This file generates the Airspace.xml file for VATSys from the UK NATS AIRAC

def airacURL():
    ## Base NATS URL
    cycle = "" # BUG: need something to calculate current cycle and autofill the base URL
    baseYear = "2020"
    baseMonth = "12"
    baseDay = "03"
    return "https://www.aurora.nats.co.uk/htmlAIP/Publications/" + baseYear + "-" + baseMonth + "-" + baseDay + "-AIRAC/html/eAIP/"

def getAiracTable(uri):
    ## Webscrape the specified page for AIRAC dataset
    URL = airacURL() + uri

    http = urllib3.PoolManager()
    error = http.request("GET", URL)
    if (error.status == 404):
        return 404
    else:
        page = requests.get(URL)
        return BeautifulSoup(page.content, "lxml")

def convertCoords(row):
    ## Get coordinates for the navaid
    coordinates = {}
    coords = row.find_all("span", class_="SD")
    for coord in coords:
        lat = coord.find(string=re.compile("(?<!Purpose\:\s)([0-9]{6}[NS]{1})"))
        lon = coord.find(string=re.compile("(?<![NS]\s)([0-9]{7}[EW]{1})"))
        if lon is not None :
            if lon.endswith("E"):
                coordinates["lon"] = ("+" + lon[0:7] + ".0") # Convert Eastings to +
            elif lon.endswith("W"):
                coordinates["lon"] = ("-" + lon[0:7] + ".0") # Convert Westings to -
        if lat is not None :
            if lat.endswith("N"):
                coordinates["lat"] = ("+" + lat[0:6] + ".0") # Convert Northings to +
            elif lat.endswith("S"):
                coordinates["lat"] = ("-" + lat[0:6] + ".0") # Convert Southings to -

    return coordinates.get("lat") + coordinates.get("lon")

def xmlRoot(name):
    ## Define the XML root tag
    xml = xtree.Element(name)
    xml.set('xmlns:xsd', 'http://www.w3.org/2001/XMLSchema')
    xml.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

    ## Set a tag for XML generation time
    xml.set('generated', ctime(time()))

    return xml

def enr41(table):
    ## For every row that is found, do...
    children = []
    for row in table:
        ## Get the row id which provides the name and navaid type
        id = row['id']
        name = id.split('-')

        fullCoord = convertCoords(row)

        ## Set the navaid type correctly
        if name[1] == "VORDME":
            name[1] = "VOR"
        elif name[1] == "DME":
            name[1] = "VOR"

        ## Construct the element
        xmlC = xtree.SubElement(xmlIntersections, 'Point')
        xmlC.set('Name', name[2])
        xmlC.set('Type', 'Navaid')
        xmlC.set('NavaidType', name[1])
        xmlC.text = fullCoord
        children.append(xmlC)

    return children

def enr44(table):
    ## For every row that is found, do...
    children = []
    for row in table:
        ## Get the row id which provides the name and navaid type
        id = row['id']
        name = id.split('-')

        fullCoord = convertCoords(row)

        ## Construct the element
        xmlC = xtree.SubElement(xmlIntersections, 'Point')
        xmlC.set('Name', name[1])
        xmlC.set('Type', 'Fix')
        xmlC.text = fullCoord
        children.append(xmlC)

    return children

## Define XML top level tag
xmlAirspace = xmlRoot('Airspace')

##########################################################################################################
## Define the XML sub tag 'SystemRunways' - https://virtualairtrafficsystem.com/docs/dpk/#systemrunways ##
##########################################################################################################
xmlSystemRunways = xtree.SubElement(xmlAirspace, 'SystemRunways')

## Get AD2 aerodrome list from AD0.6 table
print("Processing EG-AD-0.6 Data...")
getAerodromeList = getAiracTable("EG-AD-0.6-en-GB.html")
listAerodromeList = getAerodromeList.find_all("tr")

## Place aerodrome list into a set
fullAerodromeList = {"EGLL", "EGKK"}
for row in listAerodromeList:
    getAerodrome = row.find(string=re.compile("(EG)[A-Z]{2}$"))
    if getAerodrome is not None:
        fullAerodromeList.add(getAerodrome)

## Find out how many areodromes are in the list
numberOfAerodromes = len(fullAerodromeList)

with alive_bar(numberOfAerodromes + 2) as bar:
    for aerodrome in fullAerodromeList:
        ## Place a full list of runways into a set
        fullRunwayList = {"EGLL-26L", "EGLL-26R"}
        ## list all aerodrome runways
        bar() # progress the progress bar
        getRunways = getAiracTable("EG-AD-2."+ aerodrome +"-en-GB.html")
        if getRunways != 404:
            ## Construct the XML element as per https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
            xmlAerodrome = xtree.SubElement(xmlSystemRunways, 'Airport')
            xmlAerodrome.set('Name', aerodrome)
            print("Processing EG-AD-2 Data for "+ aerodrome +"...")
            aerodromeRunways = getRunways.find(id=aerodrome + "-AD-2.12")

            for rwy in aerodromeRunways:
                addRunway = rwy.find_all(string=re.compile("(RWY)\s[0-3]{1}[0-9]{1}[L|R|C]?$"))
                for a in addRunway:
                    if a is not None:
                        rwyDes = a.split()
                        fullRunwayList.add(aerodrome + "-" + rwyDes[1])
                        ## Add to XML construct
                        xmlRunway = xtree.SubElement(xmlAerodrome, 'Runway')
                        xmlRunway.set('Name', rwyDes[1])
                        xmlRunway.set('DataRunway', rwyDes[1])
                        xmlAerodrome.extend(xmlRunway)
        else:
            print(Fore.RED + "Aerodrome " + aerodrome + " does not exist" + Style.RESET_ALL)

    xmlSystemRunways.extend(xmlAerodrome)

##########################################################################################################
## Define the XML sub tag 'Intersections' - https://virtualairtrafficsystem.com/docs/dpk/#intersections ##
##########################################################################################################
    xmlIntersections = xtree.SubElement(xmlAirspace, 'Intersections')

    ## Get ENR-4.1 data from the defined website
    print("Processing EG-ENR-4.1 Data...")
    getENR41 = getAiracTable("EG-ENR-4.1-en-GB.html")
    listENR41 = getENR41.find_all("tr", class_ = "Table-row-type-3")
    getChildren = enr41(listENR41)
    xmlIntersections.extend(getChildren)
    bar() # progress the progress bar

    ## Get ENR-4.4 data from the defined website
    print("Processing EG-ENR-4.4 Data...")
    getENR44 = getAiracTable("EG-ENR-4.4-en-GB.html")
    listENR44 = getENR44.find_all("tr", class_ = "Table-row-type-3")
    getChildren = enr44(listENR44)
    xmlIntersections.extend(getChildren)
    bar() # progress the progress bar

##########################################################################################################
## Define the XML sub tag 'SIDSTARs' - https://virtualairtrafficsystem.com/docs/dpk/#sidstars           ##
##########################################################################################################
# IDEA: This is currently scraping the *.ese file from VATSIM-UK. Need to find a better way of doing this. Too much hard code here and it's lazy!
    xmlSidStar = xtree.SubElement(xmlAirspace, 'SIDSTARs')

    ese = open("UK.ese", "r")
    for line in ese:
        ## Pull out all SIDs
        if line.startswith("SID"):
            element = line.split(":")
            areodrome = element[1]
            runway = element[2]
            sid = element[3]
            route = element[4]

            ## Add to XML construct
            xmlSid = xtree.SubElement(xmlSidStar, 'SID')
            xmlSid.set('Name', sid)
            xmlSid.set('Airport', areodrome)
            xmlRoute = xtree.SubElement(xmlSid, "Route")
            xmlRoute.set("Runway", runway)
            xmlRoute.text = route
            xmlSid.extend(xmlRoute)
        xmlSidStar.extend(xmlSid)

##########################################################################################################
## Close everything off and export                                                                      ##
##########################################################################################################
tree = xtree.ElementTree(xmlAirspace)
tree.write('export.xml', encoding="utf-8", xml_declaration=True)
