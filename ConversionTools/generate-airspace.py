#! /usr/bin/python3
import sys
import requests
import re
import prettierfier as pretty
import xml.etree.ElementTree as xtree
import urllib3
import mysql.connector
import mysqlconnect ## mysql connection details
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

        ## Add navaid to the aerodromeDB
        sql = "INSERT INTO navaids (name, type, coords) SELECT * FROM (SELECT '"+ str(name[2]) +"' AS srcName, '"+ str(name[1]) +"' AS srcType, '"+ str(fullCoord) +"' AS srcCoord) AS tmp WHERE NOT EXISTS (SELECT name FROM navaids WHERE name =  '"+ str(name[2]) +"' AND type =  '"+ str(name[1]) +"' AND coords = '"+ str(fullCoord) +"') LIMIT 1"
        mysqlExec(sql, "insertUpdate")

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

        ## Add fix to the aerodromeDB
        sql = "INSERT INTO fixes (name, coords) SELECT * FROM (SELECT '"+ str(name[1]) +"' AS srcName, '"+ str(fullCoord) +"' AS srcCoord) AS tmp WHERE NOT EXISTS (SELECT name FROM fixes WHERE name =  '"+ str(name[1]) +"' AND coords = '"+ str(fullCoord) +"') LIMIT 1"
        mysqlExec(sql, "insertUpdate")

        ## Construct the element
        xmlC = xtree.SubElement(xmlIntersections, 'Point')
        xmlC.set('Name', name[1])
        xmlC.set('Type', 'Fix')
        xmlC.text = fullCoord
        children.append(xmlC)

    return children

def mysqlExec(sql, type):
    try:
        if type == "insertUpdate":
            cursor.execute(sql)
            mysqlconnect.db.commit()
        elif type == "selectOne":
            cursor.execute(sql)
            return cursor.fetchone()
        elif type == "selectMany":
            cursor.execute(sql)
            return cursor.fetchall()
    except mysql.connector.Error as err:
        print(err)

## Define XML top level tag
xmlAirspace = xmlRoot('Airspace')

cursor = mysqlconnect.db.cursor()

##########################################################################################################
## Define the XML sub tag 'SystemRunways' - https://virtualairtrafficsystem.com/docs/dpk/#systemrunways ##
##########################################################################################################
xmlSystemRunways = xtree.SubElement(xmlAirspace, 'SystemRunways')

## Get AD2 aerodrome list from AD0.6 table
print("Processing EG-AD-0.6 Data...")
getAerodromeList = getAiracTable("EG-AD-0.6-en-GB.html")

listAerodromeList = getAerodromeList.find_all("tr") # IDEA: Think there is a more efficient way of parsing this data

for row in listAerodromeList:
    aerodromeCount = 0
    getAerodrome = row.find(string=re.compile("^(EG)[A-Z]{2}$"))
    if getAerodrome is not None:
        ## Place each aerodrome into the DB
        sql = "INSERT INTO aerodromes (icao_designator, verified) VALUES ('"+ getAerodrome +"' , 0)"
        mysqlExec(sql, "insertUpdate")

## Count the number of aerodromes
sql = "SELECT COUNT(icao_designator) AS NumberofAerodromes FROM aerodromes"
numberofAerodromes = mysqlExec(sql, "selectOne")

with alive_bar(numberofAerodromes[0]) as bar: ## Define the progress bar
    ## Select all aerodromes and loop through
    sql = "SELECT id, icao_designator FROM aerodromes"
    tableAerodrome = mysqlExec(sql, "selectMany")

    for aerodrome in tableAerodrome:
        ## list all aerodrome runways
        bar() # progress the progress bar
        getRunways = getAiracTable("EG-AD-2."+ aerodrome[1] +"-en-GB.html") ## Try and find all runways at this aerodrome
        if getRunways != 404:
            ## Add verify flag for this aerodrome
            sql = "UPDATE aerodromes SET verified = 1 WHERE id = '"+ str(aerodrome[0]) +"'"
            mysqlExec(sql, "insertUpdate")

            ## Construct the XML element as per https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
            xmlAerodrome = xtree.SubElement(xmlSystemRunways, 'Airport')
            xmlAerodrome.set('Name', aerodrome[1])
            print("Processing EG-AD-2 Data for "+ aerodrome[1] +"...")
            aerodromeRunways = getRunways.find(id=aerodrome[1] + "-AD-2.12")

            for rwy in aerodromeRunways:
                addRunway = rwy.find_all(string=re.compile("(RWY)\s[0-3]{1}[0-9]{1}[L|R|C]?$")) ## String to search for runway designations
                for a in addRunway:
                    if a is not None:
                        rwyDes = a.split()
                        ## Add runway to the aerodromeDB
                        sql = "INSERT INTO aerodrome_runways (aerodrome_id, runway) SELECT * FROM (SELECT '"+ str(aerodrome[0]) +"' AS airid, '"+ str(rwyDes[1]) +"' AS rwy) AS tmp WHERE NOT EXISTS (SELECT aerodrome_id FROM aerodrome_runways WHERE aerodrome_id =  '"+ str(aerodrome[0]) +"' AND runway = '"+ str(rwyDes[1]) +"') LIMIT 1"
                        mysqlExec(sql, "insertUpdate")

                        ## Add to XML construct
                        xmlRunway = xtree.SubElement(xmlAerodrome, 'Runway')
                        xmlRunway.set('Name', rwyDes[1])
                        xmlRunway.set('DataRunway', rwyDes[1])
                        xmlAerodrome.extend(xmlRunway)
        else:
            ## Remove verify flag for this aerodrome
            sql = "UPDATE aerodromes SET verified = 0 WHERE id = '"+ str(aerodrome[0]) +"'"
            mysqlExec(sql, "insertUpdate")
            print(Fore.RED + "Aerodrome " + aerodrome[1] + " does not exist" + Style.RESET_ALL)

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
            aerodrome = str(element[1])
            runway = str(element[2])
            sid = str(element[3])
            routeComment = str(element[4])
            routeSplit = routeComment.split(";")
            route = routeSplit[0]

            if not sid.startswith('#'): ## try and exclude any commented out sections from the ese file
                sql = "SELECT aerodrome_runways.id FROM aerodromes INNER JOIN aerodrome_runways ON aerodromes.id = aerodrome_runways.aerodrome_id WHERE aerodromes.icao_designator = '"+ aerodrome +"' AND aerodrome_runways.runway = '"+ runway +"' LIMIT 1"
                rwyId = mysqlExec(sql, "selectOne")

                try:
                    sql = "INSERT INTO aerodrome_runways_sid (runway_id, sid, route) SELECT * FROM (SELECT '"+ str(rwyId[0]) +"' AS selRwyId, '"+ sid +"' AS selSid, '"+ route +"' AS selRoute) AS tmp WHERE NOT EXISTS (SELECT runway_id FROM aerodrome_runways_sid WHERE runway_id =  "+ str(rwyId[0]) +" AND sid = '"+ sid +"' AND route = '"+ route +"') LIMIT 1"
                    mysqlExec(sql, "insertUpdate")

                    ## Add to XML construct
                    xmlSid = xtree.SubElement(xmlSidStar, 'SID')
                    xmlSid.set('Name', sid)
                    xmlSid.set('Airport', aerodrome)
                    xmlRoute = xtree.SubElement(xmlSid, "Route")
                    xmlRoute.set("Runway", runway)
                    xmlRoute.text = route
                    xmlSid.extend(xmlRoute)
                    xmlSidStar.extend(xmlSid)
                except:
                    print(Fore.RED + "Aerodrome ICAO " + aerodrome + " not recognised" + Style.RESET_ALL)
                    print(line)

            bar() # progress the progress bar

        elif line.startswith("STAR"):
            element = line.split(":")
            aerodrome = str(element[1])
            runway = str(element[2])
            star = str(element[3])
            routeComment = str(element[4])
            routeSplit = routeComment.split(";")
            route = routeSplit[0]

            if not star.startswith('#'): ## try and exclude any commented out sections from the ese file
                sql = "SELECT aerodrome_runways.id FROM aerodromes INNER JOIN aerodrome_runways ON aerodromes.id = aerodrome_runways.aerodrome_id WHERE aerodromes.icao_designator = '"+ aerodrome +"' AND aerodrome_runways.runway = '"+ runway +"' LIMIT 1"
                rwyId = mysqlExec(sql, "selectOne")

                try:
                    sql = "INSERT INTO aerodrome_runways_star (runway_id, star, route) SELECT * FROM (SELECT '"+ str(rwyId[0]) +"' AS selRwyId, '"+ star +"' AS selSid, '"+ route +"' AS selRoute) AS tmp WHERE NOT EXISTS (SELECT runway_id FROM aerodrome_runways_star WHERE runway_id =  "+ str(rwyId[0]) +" AND star = '"+ star +"' AND route = '"+ route +"') LIMIT 1"
                    mysqlExec(sql, "insertUpdate")

                    ## Add to XML construct
                    xmlStar = xtree.SubElement(xmlStarStar, 'SID')
                    xmlStar.set('Name', star)
                    xmlStar.set('Airport', aerodrome)
                    xmlRoute = xtree.SubElement(xmlStar, "Route")
                    xmlRoute.set("Runway", runway)
                    xmlRoute.text = route
                    xmlStar.extend(xmlRoute)
                    xmlStarStar.extend(xmlStar)
                except:
                    print(Fore.RED + "Aerodrome ICAO " + aerodrome + " not recognised" + Style.RESET_ALL)
                    print(line)

            bar() # progress the progress bar

##########################################################################################################
## Close everything off and export                                                                      ##
##########################################################################################################
tree = xtree.ElementTree(xmlAirspace)
tree.write('export.xml', encoding="utf-8", xml_declaration=True)
