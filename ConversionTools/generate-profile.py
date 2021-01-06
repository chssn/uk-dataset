#! /usr/bin/python3
import argparse
import requests
import re
import os
import fnmatch
import xml.etree.ElementTree as xtree
import pandas as pd
import urllib3
import mysql.connector
import mysqlconnect # mysql connection details
import xmlschema
from defusedxml import defuse_stdlib
from datetime import datetime
from bs4 import BeautifulSoup
from colorama import Fore, Style
from time import time, ctime
from alive_progress import alive_bar
from pykml import parser
from shapely.geometry import MultiPoint


# This file generates XML files for VATSys from the UK NATS AIRAC
defuse_stdlib()
cursor = mysqlconnect.db.cursor()

# Build command line argument parser
cmdParse = argparse.ArgumentParser(description="Application to collect data from an AIRAC source and build that into xml files for use with vatSys.")
cmdParse.add_argument('-s', '--scrape', help='web scrape and build database only', action='store_true')
cmdParse.add_argument('-x', '--xml', help='build xml file from database', action='store_true')
cmdParse.add_argument('-c', '--clear', help='drop all records from the database', action='store_true')
cmdParse.add_argument('-g', '--geo', help='tool to assist with converting airport mapping from ES')
cmdParse.add_argument('-d', '--debug', help='runs the code defined in the debug section [DEV ONLY]', action='store_true')
cmdParse.add_argument('-v', '--verbose', action='store_true')
args = cmdParse.parse_args()

class Airac:
    def getUrl():
        # Base NATS URL
        #cycle = "" # BUG: need something to calculate current cycle and autofill the base URL
        baseUrl = "https://www.aurora.nats.co.uk/htmlAIP/Publications/"
        baseYear = "2020"
        baseMonth = "12"
        baseDay = "31"
        basePostString = "-AIRAC/html/eAIP/"
        return  baseUrl + baseYear + "-" + baseMonth + "-" + baseDay + basePostString

    def getTable(uri):
        # Webscrape the specified page for AIRAC dataset
        address = Airac.getUrl() + uri

        http = urllib3.PoolManager()
        error = http.request("GET", address)
        if (error.status == 404):
            return 404

        page = requests.get(address)
        return BeautifulSoup(page.content, "lxml")

    def enr41(table):
        # For every row that is found, do...
        for row in table:
            # Get the row id which provides the name and navaid type
            id = row['id']
            name = id.split('-')

            fullCoord = Geo.convertCoords(row)

            # Set the navaid type correctly
            if name[1] == "VORDME":
                name[1] = "VOR"
            elif name[1] == "DME":
                name[1] = "VOR"

            # Add navaid to the aerodromeDB
            sql = "INSERT INTO navaids (name, type, coords) SELECT * FROM (SELECT '"+ str(name[2]) +"' AS srcName, '"+ str(name[1]) +"' AS srcType, '"+ str(fullCoord) +"' AS srcCoord) AS tmp WHERE NOT EXISTS (SELECT name FROM navaids WHERE name =  '"+ str(name[2]) +"' AND type =  '"+ str(name[1]) +"' AND coords = '"+ str(fullCoord) +"') LIMIT 1"
            mysqlExec(sql, "insertUpdate")

    def enr44(table):
        # For every row that is found, do...
        for row in table:
            # Get the row id which provides the name and navaid type
            id = row['id']
            name = id.split('-')

            fullCoord = Geo.convertCoords(row)

            # Add fix to the aerodromeDB
            sql = "INSERT INTO fixes (name, coords) SELECT * FROM (SELECT '"+ str(name[1]) +"' AS srcName, '"+ str(fullCoord) +"' AS srcCoord) AS tmp WHERE NOT EXISTS (SELECT name FROM fixes WHERE name =  '"+ str(name[1]) +"' AND coords = '"+ str(fullCoord) +"') LIMIT 1"
            mysqlExec(sql, "insertUpdate")

    def search(find, name, string):
        searchString = find + "(?=<\/span>.*>" + name + ")"
        result = re.findall(rf"{str(searchString)}", str(string))

        return result

class Geo:
    def convertCoords(row):
        # Get coordinates for the navaid
        coordinates = {}
        coords = row.find_all("span", class_="SD")
        for coord in coords:
            lat = coord.find(string=re.compile(r"(?<!Purpose\:\s)([\d]{6}[NS]{1})"))
            lon = coord.find(string=re.compile(r"(?<![NS]\s)([\d]{7}[EW]{1})"))
            if lon is not None:
                if lon.endswith("E"):
                    coordinates["lon"] = ("+" + lon[0:7] + ".0") # Convert Eastings to +
                elif lon.endswith("W"):
                    coordinates["lon"] = ("-" + lon[0:7] + ".0") # Convert Westings to -
            if lat is not None:
                if lat.endswith("N"):
                    coordinates["lat"] = ("+" + lat[0:6] + ".0") # Convert Northings to +
                elif lat.endswith("S"):
                    coordinates["lat"] = ("-" + lat[0:6] + ".0") # Convert Southings to -

        return coordinates.get("lat") + coordinates.get("lon")

    def plusMinus(arg): # Turns a compass point into the correct + or - for lat and long
        if arg in ('N','E'):
            return "+"
        return "-"

    def kmlMappingConvert(fileIn):
        # Hardcoded to EGKK at the moment
        def mapLabels():
            # code to generate the map labels.
            points = MultiPoint(latLonString) # function to calculate polygon centroid
            labelPoint = points.centroid
            labelPrint = re.sub(r'[A-Z()]', '', str(labelPoint))
            labelSplit = labelPrint.split()

            xmlGroundMapInfLabelPoint = xtree.SubElement(xmlGroundMapInfLabel, 'Point')
            xmlGroundMapInfLabelPoint.set('Name', splitName[1])
            xmlGroundMapInfLabelPoint.text = "+" + str(labelSplit[0]) + re.sub(r'-0\.', '-000.', labelSplit[1])

        aerodromeIcao = "EGKK"

        xmlGround = Xml.root('Ground')
        xmlGroundMap = xtree.SubElement(xmlGround, 'Maps')

        with open(fileIn) as fobj:
            folder = parser.parse(fobj).getroot().Document

        xmlGroundMapRwy = Xml.constructMapHeader(xmlGroundMap, 'Ground_RWY', aerodromeIcao + '_SMR_RWY', '1', '+510853.0-0001125.0')
        xmlGroundMapTwy = Xml.constructMapHeader(xmlGroundMap, 'Ground_TWY', aerodromeIcao + '_SMR_TWY', '2', '+510853.0-0001125.0')
        xmlGroundMapBld = Xml.constructMapHeader(xmlGroundMap, 'Ground_BLD', aerodromeIcao + '_SMR_BLD', '1', '+510853.0-0001125.0')
        xmlGroundMapApr = Xml.constructMapHeader(xmlGroundMap, 'Ground_APR', aerodromeIcao + '_SMR_APR', '3', '+510853.0-0001125.0')
        xmlGroundMapBak = Xml.constructMapHeader(xmlGroundMap, 'Ground_BAK', aerodromeIcao + '_SMR_BAK', '4', '+510853.0-0001125.0')
        xmlGroundMapInf = Xml.constructMapHeader(xmlGroundMap, 'Ground_INF', aerodromeIcao + '_SMR_INF', '0', '+510853.0-0001125.0')
        xmlGroundMapHld = Xml.constructMapHeader(xmlGroundMap, 'Ground_INF', aerodromeIcao + '_SMR_HLD', '0', '+510853.0-0001125.0')

        xmlGroundMapInfLabel = xtree.SubElement(xmlGroundMapInf, 'Label')
        xmlGroundMapInfLabel.set('HasLeader', 'False')
        xmlGroundMapInfLabel.set('Alignment', 'Center')
        xmlGroundMapInfLabel.set('VerticalAlignment', 'Middle')

        for pm in folder.Placemark:
            name = pm.name
            splitName = str(name).split()
            if splitName[0] == "Hold":
                coords = pm.LineString.coordinates
            else:
                coords = pm.Polygon.outerBoundaryIs.LinearRing.coordinates

            search = re.finditer(r'([+|-]{1})([\d]{1}\.[\d]{10,20}),([\d]{2}\.[\d]{10,20})', str(coords))
            output = ''
            latLonString = []
            print(name)
            for line in search:
                fullLon = line.group().split(',')
                output += "+" + str(line.group(3)) + str(line.group(1)) + "00" + str(line.group(2)) + "/"
                latLonString.append((float(line.group(3)),float(fullLon[0])))

            if splitName[0] == "Rwy":
                xmlGroundInfill = xtree.SubElement(xmlGroundMapRwy, 'Infill')
                mapLabels()
            elif splitName[0] == "Twy":
                xmlGroundInfill = xtree.SubElement(xmlGroundMapTwy, 'Infill')
                mapLabels()
            elif splitName[0] == "Bld":
                xmlGroundInfill = xtree.SubElement(xmlGroundMapBld, 'Infill')
            elif splitName[0] == "Apr":
                xmlGroundInfill = xtree.SubElement(xmlGroundMapApr, 'Infill')
            elif splitName[0] == "Bak":
                xmlGroundInfill = xtree.SubElement(xmlGroundMapBak, 'Infill')
            elif splitName[0] == "Hold":
                xmlGroundInfill = xtree.SubElement(xmlGroundMapHld, 'Line')
                mapLabels()

            xmlGroundInfill.set('Name', name)
            xmlGroundInfill.text = output.rstrip('/')

        allGround = xtree.ElementTree(xmlGround)
        allGround.write('Build/Maps/'+ aerodromeIcao + '_SMR.xml', encoding="utf-8", xml_declaration=True)

    def backBearing(brg):
        if (float(brg) - 180) < 0:
            bB = float(brg) + 180.00
        else:
            bB = float(brg) - 180.00
        return round(bB, 2)

class Xml:
    def root(name):
        # Define the XML root tag
        xml = xtree.Element(name)
        xml.set('xmlns:xsd', 'http://www.w3.org/2001/XMLSchema')
        xml.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        # Set a tag for XML generation time
        xml.set('generated', ctime(time()))

        return xml

    def constructMapHeader(rootName, mapType, name, priority, center): # ref https://virtualairtrafficsystem.com/docs/dpk/#map-element
        # creates the neccessary header for XML documents in the \Maps folder
        mapHeader = xtree.SubElement(rootName, 'Map')

        mapHeader.set('Type', mapType) # The type primarily will affect the colour vatSys uses to paint the map. Colours are defined in Colours.xml.
        mapHeader.set('Name', name) # The title of the Map (as displayed to the user).
        mapHeader.set('Priority', priority) # An integer specifying the z-axis layering of the map, 0 being drawn on top of everything else.
        if center:
            mapHeader.set('Center', center) # An approximate center point of the map, used to deconflict in the event of multiple Waypoints with the same name.

        return mapHeader

    def elementPoint(sub, text):
        point = xtree.SubElement(sub, 'Point')
        point.text = text
        return point

class Profile:
    def constructXml():    # Define XML top level tag
        mapCenter = "+53.7-1.5"

        xmlAirspace = Xml.root('Airspace') # create XML document Airspace.xml
        # Define subtag SystemRunways, SidStar, Intersections, Airports and Airways - https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
        xmlSystemRunways = xtree.SubElement(xmlAirspace, 'SystemRunways')
        xmlSidStar = xtree.SubElement(xmlAirspace, 'SIDSTARs')
        xmlIntersections = xtree.SubElement(xmlAirspace, 'Intersections')
        xmlAirports = xtree.SubElement(xmlAirspace, 'Airports')
        xmlAirways = xtree.SubElement(xmlAirspace, 'Airways')

        # create XML document Maps\ALL_AIRPORTS
        xmlAllAirports = Xml.root('Maps')
        xmlAllAirportsMap = Xml.constructMapHeader(xmlAllAirports, 'System2', 'ALL_AIRPORTS', '2', mapCenter)
        xmlAllAirportsLabel = xtree.SubElement(xmlAllAirportsMap, 'Label')
        xmlAllAirportsLabel.set('HasLeader', 'true') # has a line connecting the point and label
        xmlAllAirportsLabel.set('LabelOrientation', 'NW') # where the label will be positioned in relation to the point
        xmlAllAirportsSymbol = xtree.SubElement(xmlAllAirportsMap, 'Symbol')
        xmlAllAirportsSymbol.set('Type', 'Reticle') # https://virtualairtrafficsystem.com/docs/dpk/#symbol-element

        # create XML document Maps\ALL_NAVAIDS
        xmlAllNavaids = Xml.root('Maps')
        xmlAllNavaidsMap = Xml.constructMapHeader(xmlAllNavaids, 'System', 'ALL_NAVAIDS_NAMES', '0', mapCenter)
        xmlAllNavaidsLabel = xtree.SubElement(xmlAllNavaidsMap, 'Label')
        xmlAllNavaidsLabel.set('HasLeader', 'true') # has a line connecting the point and label
        xmlAllNavaidsMapSym = Xml.constructMapHeader(xmlAllNavaidsMap, 'System', 'ALL_NAVAIDS', '0', mapCenter)
        xmlAllNavaidsSymbol = xtree.SubElement(xmlAllNavaidsMapSym, 'Symbol')
        xmlAllNavaidsSymbol.set('Type', 'Hexagon') # https://virtualairtrafficsystem.com/docs/dpk/#symbol-element
        xmlAllNavaidsSymbolH = xtree.SubElement(xmlAllNavaidsMapSym, 'Symbol')
        xmlAllNavaidsSymbolH.set('Type', 'DotFillCircle') # https://virtualairtrafficsystem.com/docs/dpk/#symbol-element

        # create XML document Maps\ALL_CTA
        xmlAllCta = Xml.root('Maps')
        xmlAllCtaMap = Xml.constructMapHeader(xmlAllCta, 'System', 'ALL_CTA', '2', mapCenter)

        # create XML document Maps\ALL_TMA
        xmlAllTma = Xml.root('Maps')
        xmlAllTmaMap = Xml.constructMapHeader(xmlAllTma, 'System', 'ALL_TMA', '2', mapCenter)

        # Construct the XML element as per https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
        # List all the verified aerodromes
        sql = "SELECT * FROM aerodromes WHERE verified = '1' ORDER BY icao_designator"
        listAerodromes = mysqlExec(sql, "selectMany")
        for aerodrome in listAerodromes:
            mapPoint = set() # create a set to store all SID/STAR waypoints for this aerodrome
            # Set airport name
            print(Fore.BLUE + "Constructing XML for " + aerodrome[1] + " ("+ str(aerodrome[0]) +")" + Style.RESET_ALL)
            xmlAerodrome = xtree.SubElement(xmlSystemRunways, 'Airport')
            xmlAerodrome.set('Name', aerodrome[1])
            xmlAirport = xtree.SubElement(xmlAirports, 'Airport')
            xmlAirport.set('ICAO', aerodrome[1])
            xmlAirport.set('Position', aerodrome[3])
            xmlAirport.set('Elevation', str(aerodrome[4]))

            # Set points in Maps\ALL_AIRPORTS.xml
            Xml.elementPoint(xmlAllAirportsLabel, aerodrome[1])
            Xml.elementPoint(xmlAllAirportsSymbol, aerodrome[1])

            # Now for the runways that form part of the aerodrome
            sqlA = "SELECT * FROM aerodrome_runways WHERE aerodrome_id = '"+ str(aerodrome[0]) +"' ORDER BY runway"
            listRunways = mysqlExec(sqlA, "selectMany")
            for runway in listRunways:
                xmlRunway = xtree.SubElement(xmlAerodrome, 'Runway')
                xmlRunway.set('Name', runway[2])
                xmlRunway.set('DataRunway', runway[2])

                # create XML maps for each runway
                #figure out the other end of the runway first
                oppEndSplit = re.match(r'([\d]{2})([L|R|C])?', runway[2])
                if int(oppEndSplit.group(1)) < 18:
                    oppEnd = int(oppEndSplit.group(1)) + 18
                else:
                    oppEnd = int(oppEndSplit.group(1)) - 18

                if oppEndSplit.group(2):
                    if oppEndSplit.group(2) == "L":
                        oppEnd = str(oppEnd).zfill(2) + "R"
                    elif oppEndSplit.group(2) == "R":
                        oppEnd = str(oppEnd).zfill(2) + "L"
                    elif oppEndSplit.group(2) == "C":
                        oppEnd = str(oppEnd).zfill(2) + "C"
                else:
                    oppEnd = str(oppEnd).zfill(2)

                xmlMapsRunway = Xml.root('Maps')
                xmlMapsRunwayMap = Xml.constructMapHeader(xmlMapsRunway, 'System', aerodrome[1] + '_TWR_RWY' + runway[2], '1', aerodrome[3])
                xmlMapsRunwayMapRwy = xtree.SubElement(xmlMapsRunwayMap, 'Runway')
                xmlMapsRunwayMapRwy.set('Name', runway[2])
                xmlMapsRunwayThresh = xtree.SubElement(xmlMapsRunwayMapRwy, 'Threshold')
                xmlMapsRunwayThresh.set('Name', runway[2])
                xmlMapsRunwayThresh.set('Position', runway[3])
                centreLineTrack = Geo.backBearing(runway[5])
                xmlMapsRunwayThresh.set('ExtendedCentrelineTrack', str(centreLineTrack))
                xmlMapsRunwayThresh.set('ExtendedCentrelineLength', "10")
                xmlMapsRunwayThresh.set('ExtendedCentrelineTickInterval', "1")
                xmlMapsRunwayThreshOpp = xtree.SubElement(xmlMapsRunwayMapRwy, 'Threshold')

                # add SIDs into the runway map
                sids = Navigraph.sidStar("Navigraph/sids.txt", aerodrome[1], runway[2])

                xmlMapsRunwaySid = Xml.constructMapHeader(xmlMapsRunway, 'System', aerodrome[1] + '_TWR_RWY' + runway[2] + "_SID", '1', aerodrome[3])
                for sid in sids['Route']:
                    xmlMapsRunwayLine = xtree.SubElement(xmlMapsRunwaySid, 'Line')
                    xmlMapsRunwayLine.text = sid

                    sidSplit = sid.split('/')
                    for point in sidSplit:
                        mapPoint.add(point)

                for i in sids.index:
                    xmlSid = xtree.SubElement(xmlRunway, 'SID')
                    xmlSid.set('Name', sids['Name'][i])

                    xmlSidStarSid = xtree.SubElement(xmlSidStar, 'SID')
                    xmlSidStarSid.set('Name', sids['Name'][i])
                    xmlSidStarSid.set('Airport', sids['ICAO'][i])
                    xmlSidStarSid.set('Runways', sids['Runway'][i])

                    xmlRoute = xtree.SubElement(xmlSidStarSid, 'Route')
                    xmlRoute.set('Runway', sids['Runway'][i])
                    slashToSpace = sids['Route'][i].replace('/', ' ')
                    xmlRoute.text = slashToSpace

                # add STARs into the runway map
                stars = Navigraph.sidStar("Navigraph/stars.txt", aerodrome[1], runway[2])

                xmlMapsRunwayStar = Xml.constructMapHeader(xmlMapsRunway, 'System', aerodrome[1] + '_TWR_RWY' + runway[2] + "_STAR", '1', aerodrome[3])
                for star in stars['Route']:
                    xmlMapsRunwayLine = xtree.SubElement(xmlMapsRunwayStar, 'Line')
                    xmlMapsRunwayLine.set('Pattern', 'Dotted')
                    xmlMapsRunwayLine.text = star

                    starSplit = star.split('/')
                    for point in starSplit:
                        mapPoint.add(point)

                for i in stars.index:
                    xmlSid = xtree.SubElement(xmlRunway, 'STAR')
                    xmlSid.set('Name', stars['Name'][i])

                    xmlSidStarStar = xtree.SubElement(xmlSidStar, 'STAR')
                    xmlSidStarStar.set('Name', stars['Name'][i])
                    xmlSidStarStar.set('Airport', stars['ICAO'][i])
                    xmlSidStarStar.set('Runways', stars['Runway'][i])

                    xmlRoute = xtree.SubElement(xmlSidStarStar, 'Route')
                    xmlRoute.set('Runway', stars['Runway'][i])
                    slashToSpace = stars['Route'][i].replace('/', ' ')
                    xmlRoute.text = slashToSpace

                sqlOpp = "SELECT * FROM aerodrome_runways WHERE aerodrome_id = '"+ str(aerodrome[0]) +"' AND runway = '"+ str(oppEnd) +"'"
                oppRunway = mysqlExec(sqlOpp, "selectOne")
                if oppRunway:
                    xmlMapsRunwayThreshOpp.set('Name', str(oppEnd))
                    xmlMapsRunwayThreshOpp.set('Position', str(oppRunway[3]))

                    # create map points and titles
                    xmlMapsRunwayPointsLabels = Xml.constructMapHeader(xmlMapsRunway, 'System', aerodrome[1] + '_TWR_RWY' + runway[2] + '_NAMES', '2', aerodrome[3])
                    xmlMapsRunwayPointsLabelsL = xtree.SubElement(xmlMapsRunwayPointsLabels, 'Label')
                    xmlMapsRunwayPoints = xtree.SubElement(xmlMapsRunwayPointsLabels, 'Symbol')
                    xmlMapsRunwayPoints.set('Type', 'HollowStar')
                    for point in mapPoint:
                        Xml.elementPoint(xmlMapsRunwayPoints, point)
                        Xml.elementPoint(xmlMapsRunwayPointsLabelsL, point)

                    # create folder structure if not exists
                    filename = 'Build/Maps/' + aerodrome[1] + '/' + aerodrome[1] + '_TWR_RWY' + runway[2] + '.xml'
                    os.makedirs(os.path.dirname(filename), exist_ok=True)
                    xmlMapsRunwayTree = xtree.ElementTree(xmlMapsRunway)
                    xmlMapsRunwayTree.write(filename, encoding="utf-8", xml_declaration=True)
                else:
                    print(Fore.RED + "No opposite runway for " + runway[3] + " at " + aerodrome[1] + Style.RESET_ALL)

                # add runway into the airspace.xml file
                xmlAirportRunway = xtree.SubElement(xmlAirport, 'Runway')
                xmlAirportRunway.set('Name', runway[2])
                xmlAirportRunway.set('Position', runway[3])

        # Construct the XML element as per https://virtualairtrafficsystem.com/docs/dpk/#intersections
        # List all the verified points
        sql = "SELECT * FROM fixes"
        listFixes = mysqlExec(sql, "selectMany")
        for fix in listFixes:
            # Set fix in main Airspace.xml
            xmlFix = xtree.SubElement(xmlIntersections, 'Point')
            xmlFix.set('Name', fix[1])
            xmlFix.set('Type', 'Fix')
            xmlFix.text = fix[2]

            # Set points in Maps\ALL_AIRPORTS.xml
            xmlAllNavaidsLabelPoint = xtree.SubElement(xmlAllNavaidsLabel, 'Point')
            xmlAllNavaidsLabelPoint.set('Name', fix[1])
            xmlAllNavaidsLabelPoint.text = fix[2]
            xmlAllNavaidsSymbolPoint = xtree.SubElement(xmlAllNavaidsSymbol, 'Point')
            xmlAllNavaidsSymbolPoint.text = fix[2]

        sql = "SELECT * FROM navaids"
        listNavAids = mysqlExec(sql, "selectMany")
        for fix in listNavAids:
            xmlFix = xtree.SubElement(xmlIntersections, 'Point')
            xmlFix.set('Name', fix[1])
            xmlFix.set('Type', 'Navaid')
            xmlFix.set('NavaidType', fix[2])
            xmlFix.text = fix[3]

            # Set points in Maps\ALL_AIRPORTS.xml
            xmlAllNavaidsLabelPoint = xtree.SubElement(xmlAllNavaidsLabel, 'Point')
            xmlAllNavaidsLabelPoint.set('Name', fix[1])
            xmlAllNavaidsLabelPoint.text = fix[3]
            xmlAllNavaidsSymbolPointH = xtree.SubElement(xmlAllNavaidsSymbolH, 'Point')
            xmlAllNavaidsSymbolPointH.text = fix[3]

        sql = "SELECT * FROM control_areas"
        listCta = mysqlExec(sql, "selectMany")
        for cta in listCta:
            xmlCta = xtree.SubElement(xmlAllCtaMap, 'Line')
            xmlCta.set('Name', cta[2])
            xmlCta.set('Pattern', 'Dashed')
            xmlCta.text = cta[3].rstrip('/')

        sql = "SELECT * FROM terminal_control_areas"
        listTma = mysqlExec(sql, "selectMany")
        for tma in listTma:
            xmlTma = xtree.SubElement(xmlAllTmaMap, 'Line')
            xmlTma.set('Name', tma[2])
            xmlTma.set('Pattern', 'Dashed')
            xmlTma.text = tma[3].rstrip('/')

        sql = "SELECT * FROM airways"
        listAirways = mysqlExec(sql, "selectMany")
        for airway in listAirways:
            xmlAirway = xtree.SubElement(xmlAirways, 'Airway')
            xmlAirway.set('Name', airway[1])
            xmlAirway.text = airway[2]

        allAirportsTree = xtree.ElementTree(xmlAllAirports)
        allAirportsTree.write('Build/Maps/ALL_AIRPORTS.xml', encoding="utf-8", xml_declaration=True)

        allCtaTree = xtree.ElementTree(xmlAllCta)
        allCtaTree.write('Build/Maps/ALL_CTA.xml', encoding="utf-8", xml_declaration=True)

        allTmaTree = xtree.ElementTree(xmlAllTma)
        allTmaTree.write('Build/Maps/ALL_TMA.xml', encoding="utf-8", xml_declaration=True)

        allNavaidsTree = xtree.ElementTree(xmlAllNavaids)
        allNavaidsTree.write('Build/Maps/ALL_NAVAIDS.xml', encoding="utf-8", xml_declaration=True)

        airspaceTree = xtree.ElementTree(xmlAirspace)
        airspaceTree.write('Build/Airspace.xml', encoding="utf-8", xml_declaration=True)
    # BUG: Probably read the whole XML through and run this regex (Runways=")([\d]{2}[L|R|C]?)([\d]{2}[L|R|C]?)(") and replace $1$2,$3$4
    def clearDatabase():
        print(Fore.RED + "!!!WARNING!!!" + Style.RESET_ALL)
        print("This will truncate (delete) the contents of all tables in this database.")
        print("Are you sure you wish to contine?")
        print("Please type 'confirm' to continue or any other option to leave the database intact: ")
        confirmation = input()
        if confirmation == "confirm":
            # Back everything up first!
            sqlA = "BACKUP DATABASE uk-dataset TO DISK 'backup.sql'"
            #cursor.execute(sqlA)
            tables = ["aerodromes", "aerodrome_frequencies", "aerodrome_runways", "aerodrome_runways_sid", "aerodrome_runways_star", "fixes", "navaids", "control_areas", "terminal_control_areas", "flight_information_regions", "airways"]
            for t in tables:
                truncate = "TRUNCATE TABLE " + t
                cursor.execute(truncate)
        else:
            print("No data has been deleted. We think...")

    def createFrequencies(): # creates the frequency secion of ATIS.xml, Sectors.xml
        def myround(x, base=0.025): # rounds to the nearest 25KHz - simulator limitations prevent 8.33KHz spacing currently
            flt = float(x)
            return base * round(flt/base)

        xmlSectors = Xml.root("Sectors")
        lastType = ''

        sql = "SELECT aerodromes.icao_designator, aerodromes.name, aerodrome_frequencies.frequency, standard_callsigns.callsign_postfix, standard_callsigns.description FROM aerodromes INNER JOIN aerodrome_frequencies ON aerodromes.id = aerodrome_frequencies.aerodrome_id INNER JOIN standard_callsigns ON aerodrome_frequencies.callsign_type_id = standard_callsigns.id ORDER BY `aerodromes`.`name`, standard_callsigns.description ASC"
        frequencies = mysqlExec(sql, "selectMany")

        for freq in frequencies:
            if freq[3] != lastType:
                freq25khz = myround(freq[2])
                if freq[3] != "_ATIS":
                    xmlSector = xtree.SubElement(xmlSectors, "Sector")
                    xmlSector.set('FullName', freq[1] + " " + freq[4]) # eg LONDON GATWICK GROUND
                    xmlSector.set('Frequency', "%.3f" % freq25khz) # format to full frequency eg 122.800
                    xmlSector.set('Callsign', freq[0] + freq[3]) # eg EGKK_GND
                    xmlSector.set('Name', freq[0] + freq[3])
                    print(freq[1] + ' ' + freq[4] + "|" + "%.3f" % freq25khz + "|" + freq[0] + freq[3])

                    # cascade for ResponsibleSectors tag in Sectors.xml
                    xmlSectorResponsible = xtree.SubElement(xmlSector, "ResponsibleSectors")
                    if freq[3] == "_D_APP":
                        xmlSectorResponsible.text = freq[0] + "_APP," + freq[0] + "_TWR," + freq[0] + "_GND," + freq[0] + "_DEL"
                    elif freq[3] == "_APP":
                        xmlSectorResponsible.text = freq[0] + "_TWR," + freq[0] + "_GND," + freq[0] + "_DEL"
                    elif freq[3] == "_TWR":
                        xmlSectorResponsible.text = freq[0] + "_GND," + freq[0] + "_DEL"
                    elif freq[3] == "_GND":
                        xmlSectorResponsible.text = freq[0] + "_DEL"

                lastType = freq[3]

        sectorTree = xtree.ElementTree(xmlSectors)
        sectorTree.write('Build/Sectors.xml', encoding="utf-8", xml_declaration=True)

    def createRadars():
        sql = "SELECT * FROM radar_sites"
        radarSites = mysqlExec(sql, "selectMany")

        xmlAllRadars = Xml.root("Radars")

        for radar in radarSites:
            xmlRadar = xtree.SubElement(xmlAllRadars, 'Radar')
            xmlRadar.set('Name', str(radar[1]))
            xmlRadar.set('Type', str(radar[5]))
            xmlRadar.set('Elevation', str(radar[4]))
            xmlRadar.set('MaxRange', str(radar[6]))

            xmlRadarLat = xtree.SubElement(xmlRadar, 'Lat')
            xmlRadarLat.text = str(radar[2])
            xmlRadarLong = xtree.SubElement(xmlRadar, 'Long')
            xmlRadarLong.text = str(radar[3])

            radarTree = xtree.ElementTree(xmlAllRadars)
            radarTree.write('Build/Radars.xml', encoding="utf-8", xml_declaration=True)

class WebScrape:
    def main():
        # Count the number of ICAO designators (may not actually be a verified aerodrome)
        sql = "SELECT COUNT(icao_designator) AS NumberofAerodromes FROM aerodromes"
        numberofAerodromes = mysqlExec(sql, "selectOne")

        with alive_bar(numberofAerodromes[0]) as bar: # Define the progress bar
            # Select all aerodromes and loop through
            sql = "SELECT id, icao_designator FROM aerodromes"
            tableAerodrome = mysqlExec(sql, "selectMany")

            for aerodrome in tableAerodrome:    # AD 2 data
                # list all aerodrome runways
                bar() # progress the progress bar
                getRunways = Airac.getTable("EG-AD-2."+ aerodrome[1] +"-en-GB.html") # Try and find all information for this aerodrome
                if getRunways != 404:
                    print("Parsing EG-AD-2 Data for "+ aerodrome[1] +"...")
                    aerodromeLocation = getRunways.find(id=aerodrome[1] + "-AD-2.2")
                    aerodromeAD212 = getRunways.find(id=aerodrome[1] + "-AD-2.12")
                    aerodromeAD218 = getRunways.find(id=aerodrome[1] + "-AD-2.18")

                    # Parse current magnetic variation
                    aerodromeMagVar = Airac.search("([\d]{1}\.[\d]{2}).([W|E]{1})", "TAD_HP;VAL_MAG_VAR", str(aerodromeLocation))
                    pM = Geo.plusMinus(aerodromeMagVar[0][1])
                    floatMagVar = pM + aerodromeMagVar[0][0]

                    # Add verify flag and magnetic variation for this aerodrome
                    sql = "UPDATE aerodromes SET verified = 1, magnetic_variation = '"+ str(floatMagVar) +"' WHERE id = '"+ str(aerodrome[0]) +"'"
                    mysqlExec(sql, "insertUpdate")

                    # Parse runway locations
                    aerodromeRunways = Airac.search("([\d]{2}[L|C|R]?)", "TRWY_DIRECTION;TXT_DESIG", str(aerodromeAD212))
                    aerodromeRunwaysLat = Airac.search("([\d]{6}\.[\d]{2}[N|S]{1})", "TRWY_CLINE_POINT;GEO_LAT", str(aerodromeAD212))
                    aerodromeRunwaysLong = Airac.search("([\d]{7}\.[\d]{2}[E|W]{1})", "TRWY_CLINE_POINT;GEO_LONG", str(aerodromeAD212))
                    aerodromeRunwaysElev = Airac.search("([\d]{3})", "TRWY_CLINE_POINT;VAL_GEOID_UNDULATION", str(aerodromeAD212))
                    aerodromeRunwaysBearing = Airac.search("([\d]{3}\.[\d]{2}.)", "TRWY_DIRECTION;VAL_TRUE_BRG", str(aerodromeAD212))
                    aerodromeRunwaysLen = Airac.search("([\d]{3,4})", "TRWY;VAL_LEN", str(aerodromeAD212))

                    if args.verbose:
                        print(aerodromeRunways)
                        print(aerodromeRunwaysLat)
                        print(aerodromeRunwaysLong)
                        print(aerodromeRunwaysElev)
                        print(aerodromeRunwaysBearing)
                        print(aerodromeRunwaysLen)

                    for rwy, lat, lon, elev, brg, rwyLen in zip(aerodromeRunways, aerodromeRunwaysLat, aerodromeRunwaysLong, aerodromeRunwaysElev, aerodromeRunwaysBearing, aerodromeRunwaysLen):
                        # Add runway to the aerodromeDB
                        latSplit = re.search(r"([\d]{6}\.[\d]{2})([N|S]{1})", str(lat))
                        lonSplit = re.search(r"([\d]{7}\.[\d]{2})([E|W]{1})", str(lon))
                        latPM = Geo.plusMinus(latSplit.group(2))
                        lonPM = Geo.plusMinus(lonSplit.group(2))
                        loc = str(latPM) + str(latSplit.group(1)) + str(lonPM) + str(lonSplit.group(1)) # build lat/lon string as per https://virtualairtrafficsystem.com/docs/dpk/#lat-long-format

                        sql = "INSERT INTO aerodrome_runways (aerodrome_id, runway, location, elevation, bearing, length) VALUE ('"+ str(aerodrome[0]) +"', '"+ str(rwy) +"', '"+ str(loc) +"', '"+ str(elev) +"', '"+ str(brg.rstrip('°')) +"', '"+ str(rwyLen) +"')"
                        mysqlExec(sql, "insertUpdate")

                    # Parse air traffic services
                    aerodromeServices = Airac.search("(APPROACH|GROUND|DELIVERY|TOWER|DIRECTOR|INFORMATION)", "TCALLSIGN_DETAIL", str(aerodromeAD218))
                    serviceFrequency = Airac.search("([\d]{3}\.[\d]{3})", "TFREQUENCY", str(aerodromeAD218))

                    for srv, frq in zip(aerodromeServices, serviceFrequency):
                        callSignId = "SELECT id FROM standard_callsigns WHERE description = '"+ str(srv) +"' LIMIT 1"
                        callSignType = mysqlExec(callSignId, "selectOne")
                        csModify = re.search(r"([\d]{1,8})", str(callSignType))

                        sql = "INSERT INTO aerodrome_frequencies (aerodrome_id, callsign_type_id, frequency) VALUE ('"+ str(aerodrome[0]) +"', '"+ str(csModify.group(1)) +"', '"+ str(frq) +"')"
                        mysqlExec(sql, "insertUpdate")

                    # Search for aerodrome lat/lon/elev
                    aerodromeLat = re.search(r'(Lat: )(<span class="SD" id="ID_[\d]{7}">)([\d]{6})([N|S]{1})', str(aerodromeLocation))
                    aerodromeLon = re.search(r"(Long: )(<span class=\"SD\" id=\"ID_[\d]{7}\">)([\d]{7})([E|W]{1})", str(aerodromeLocation))
                    aerodromeElev = re.search(r"(VAL_ELEV\;)([\d]{1,4})", str(aerodromeLocation))

                    if aerodromeLat:
                        latPM = Geo.plusMinus(aerodromeLat.group(4))
                    else:
                        latPM = "+" # BUG: lazy fail option

                    if aerodromeLon:
                        lonPM = Geo.plusMinus(aerodromeLon.group(4))
                    else:
                        lonPM = "-" # BUG: Lazy fail option

                    fullLocation = latPM + aerodromeLat.group(3) + ".0" + lonPM + aerodromeLon.group(3) + ".0"

                    sql = "UPDATE aerodromes SET location = '"+ str(fullLocation) +"', elevation = '"+ aerodromeElev[2] +"' WHERE id = '"+ str(aerodrome[0]) +"'"
                    mysqlExec(sql, "insertUpdate")
                else:
                    # Remove verify flag for this aerodrome
                    sql = "UPDATE aerodromes SET verified = 0 WHERE id = '"+ str(aerodrome[0]) +"'"
                    mysqlExec(sql, "insertUpdate")
                    print(Fore.RED + "Aerodrome " + aerodrome[1] + " does not exist" + Style.RESET_ALL)

            # Get ENR-4.1 data from the defined website
            print("Parsing EG-ENR-4.1 Data (RADIO NAVIGATION AIDS - EN-ROUTE)...")
            getENR41 = Airac.getTable("EG-ENR-4.1-en-GB.html")
            listENR41 = getENR41.find_all("tr", class_ = "Table-row-type-3")
            Airac.enr41(listENR41)
            bar() # progress the progress bar

            # Get ENR-4.4 data from the defined website
            print("Parsing EG-ENR-4.4 Data (NAME-CODE DESIGNATORS FOR SIGNIFICANT POINTS)...")
            getENR44 = Airac.getTable("EG-ENR-4.4-en-GB.html")
            listENR44 = getENR44.find_all("tr", class_ = "Table-row-type-3")
            Airac.enr44(listENR44)
            bar() # progress the progress bar

    def firUirTmaCtaData():
        def getBoundary(space): # creates a boundary useable in vatSys from AIRAC data
            lat = 1
            fullBoundary = ''
            for s in space:
                if s[1] == "W" or s[1] == "S":
                    symbol = "-"
                else:
                    symbol = "+"

                if lat == 1:
                    coordString = symbol + s[0] + ".00"
                    lat = 0
                else:
                    coordString += symbol + s[0]
                    fullBoundary += coordString + ".00/"
                    lat = 1

            return fullBoundary.rstrip('/')

        print("Parsing EG-ENR-2.1 Data (FIR, UIR, TMA AND CTA)...")
        getENR21 = Airac.getTable("EG-ENR-2.1-en-GB.html")
        listENR21 = getENR21.find_all("td")
        barLength = len(listENR21)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in listENR21:
                # find all FIR spaces
                firTitle = Airac.search("([A-Z]*\sFIR)", "TAIRSPACE;TXT_NAME", str(row))
                firSpace = Airac.search("([\d]{6,7})([N|E|S|W]{1})", "TAIRSPACE_VERTEX;GEO_L", str(row))
                firUpper = Airac.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_LAYER;VAL_DIST_VER_UPPER", str(row))
                firLower = Airac.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_LAYER;VAL_DIST_VER_LOWER", str(row))
                if not firUpper:
                    firUpper = Airac.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_VOLUME;VAL_DIST_VER_UPPER", str(row))
                    firLower = Airac.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_VOLUME;VAL_DIST_VER_LOWER", str(row))
                    if not firLower:
                        firLower = "0"

                if firTitle:
                    if firSpace:
                        boundary = getBoundary(firSpace)
                        sqlF = "INSERT INTO flight_information_regions (name, callsign, frequency, boundary, upper_fl, lower_fl) VALUE ('"+ str(firTitle[0]) +"', 'NONE', '000.000', '"+ str(boundary) +"', '"+ str(firUpper[0]) +"', '"+ str(firLower[0]) +"')"
                        mysqlExec(sqlF, "insertUpdate")
                        # lazy bit of coding for EG airspace UIR (which has the same extent as FIR)
                        sqlU = "INSERT INTO flight_information_regions (name, callsign, frequency, boundary, upper_fl, lower_fl) VALUE ('"+ str(firTitle[0]).split()[0] +" UIR', 'NONE', '000.000', '"+ str(boundary) +"', '660', '245')"
                        mysqlExec(sqlU, "insertUpdate")

                # find all CTA spaces
                ctaTitle = Airac.search("([A-Z\s]*)(\sCTA\s)([\d]?)", "TAIRSPACE;TXT_NAME", str(row))
                ctaSpace = Airac.search("([\d]{6,7})([N|E|S|W]{1})", "TAIRSPACE_VERTEX;GEO_L", str(row))
                ctaCircle = re.search("circle", str(row))
                if ctaTitle:
                    if not ctaCircle:
                        fF = re.search(r"(\')([A-Z\s]*)(\')(.*)(\sCTA\s)(.*)([\d]{1,2}?)", str(ctaTitle))
                        try:
                            title = str(fF.group(2)) + str(fF.group(5)) + str(fF.group(7))
                        except:
                            title = str(fF.group(2)) + str(fF.group(5))

                        if ctaSpace:
                            boundary = getBoundary(ctaSpace)

                            sql = "INSERT INTO control_areas (fir_id, name, boundary) VALUE ('0', '"+ str(title) +"', '"+ str(boundary) +"')"
                            mysqlExec(sql, "insertUpdate")
                    else:
                        print(str(ctaTitle) + " complex CTA")

                # find all TMA spaces
                tmaTitle = Airac.search("([A-Z\s]*)(\sTMA\s)([\d]?)", "TAIRSPACE;TXT_NAME", str(row))
                tmaSpace = Airac.search("([\d]{6,7})([N|E|S|W]{1})", "TAIRSPACE_VERTEX;GEO_L", str(row))
                tmaCircle = re.search("circle", str(row))
                if tmaTitle:
                    if not tmaCircle:
                        fF = re.search(r"(\')([A-Z\s]*)(\')(.*)(\sTMA\s)(.*)([\d]{1,2}?)", str(tmaTitle))
                        try:
                            title = str(fF.group(2)) + str(fF.group(5)) + str(fF.group(7))
                        except:
                            title = str(fF.group(2)) + str(fF.group(5))

                        if tmaSpace:
                            boundary = getBoundary(tmaSpace)

                            sql = "INSERT INTO terminal_control_areas (fir_id, name, boundary) VALUE ('0', '"+ str(title) +"', '"+ str(boundary) +"')"
                            mysqlExec(sql, "insertUpdate")
                    else:
                        print(str(tmaTitle) + " complex TMA")
                bar()

    def processAd06Data():
        print("Parsing EG-AD-0.1 data to obtain ICAO designators...")
        getAerodromeList = Airac.getTable("EG-AD-0.1-en-GB.html")
        listAerodromeList = getAerodromeList.find_all("h3") # IDEA: Think there is a more efficient way of parsing this data
        for row in listAerodromeList:
            getAerodrome = re.search(r"([A-Z]{4})(\n[\s\S]{7}\n[\s\S]{8})([A-Z]{4}.*)(\n[\s\S]{6}<\/a>)", str(row))
            if getAerodrome:
                # Place each aerodrome into the DB
                sql = "INSERT INTO aerodromes (icao_designator, verified, location, elevation, name) VALUES ('"+ str(getAerodrome[1]) +"' , 0, 0, 0, '"+ str(getAerodrome[3]) +"')"
                mysqlExec(sql, "insertUpdate")  # Process data from AD 0.6

    def parseUKMil():
        # this is a hard-coded bodge for getting UK military ICAO designators.
        url = "https://www.aidu.mod.uk/aip/aipVolumes.htm"
        http = urllib3.PoolManager()
        error = http.request("GET", url)
        if (error.status == 404):
            return 404

        page = requests.get(url)
        source = BeautifulSoup(page.content, "lxml")
        getICAO = re.findall(r'(?<=\")([L|E|F]{1}[A-Z]{3})(?=\")', source) # L, E and F are to include British Overseas Territory listed here

        for icao in getICAO:
            # Place each aerodrome into the DB
            sql = "INSERT INTO aerodromes (icao_designator, verified, location, elevation) VALUES ('"+ icao +"' , 0, 0, 0)"
            mysqlExec(sql, "insertUpdate")

                #getLinks = re.findall(r'(?<=aip\/pdf\/ad\/)'+ icao + '')
                # IDEA: Need to code this bit properly - placeholder for now

    def parseENR3(section):
        print("Parsing EG-ENR-3."+ section +" data to obtain ATS routes...")
        getENR3 = Airac.getTable("EG-ENR-3."+ section +"-en-GB.html")
        listTables = getENR3.find_all("tbody")
        for row in listTables:
            getAirwayName = Airac.search("([A-Z]{1,2}[\d]{1,4})", "TEN_ROUTE_RTE;TXT_DESIG", str(row))
            getAirwayRoute = Airac.search("([A-Z]{3,5})", "T(DESIGNATED_POINT|DME|VOR|NDB);CODE_ID", str(row))
            printRoute = ''
            if getAirwayName:
                for point in getAirwayRoute:
                    printRoute += str(point[0]) + "/"
                sql = "INSERT INTO airways (name, route) VALUES ('"+ str(getAirwayName[0]) +"', '"+ str(printRoute).rstrip('/') +"')"
                mysqlExec(sql, "insertUpdate")

class EuroScope:
    def parse(fileIn):
        file = open(fileIn, "r")
        output = ""
        for f in file:
            coord = re.search(r"(N|S)([\d]{3})\.([\d]{2})\.([\d]{2})(\.[\d]{3})\s(E|W)([\d]{3})\.([\d]{2})\.([\d]{2})(\.[\d]{3})", f)
            latSign = Geo.plusMinus(coord.group(1))
            lonSign = Geo.plusMinus(coord.group(6))

            output += latSign + coord.group(2).lstrip("0") + coord.group(3) + coord.group(4)  + coord.group(5) + lonSign + coord.group(7) + coord.group(8) + coord.group(9)  + coord.group(10) + "/"

        print(output.rstrip("/"))

class Navigraph:
    def sidStar(file, icaoIn, rwyIn):
        dfColumns=['ICAO','Runway','Name','Route']
        df = pd.DataFrame(columns=dfColumns)
        #print(df.to_string())
        with open(file, 'r') as text:
            content = text.read() # read everything
            aerodromeData = re.split(r'\[', content) # split by [
            for data in aerodromeData:
                aerodromeIcao = re.search(r'([A-Z]{4})(\]\n)', data) # get the ICAO aerodrome designator
                if aerodromeIcao:
                    icao = aerodromeIcao.group(1)
                    if icao == icaoIn:
                        lineSearch = re.findall(r'(T[\s]+)([A-Z\d]{5,})([\s]+[A-Z\d]{5,}[\s]+)([\d]{2}[L|R|C]?)(\,.*)?\n', data)

                        if lineSearch:
                            for line in lineSearch:
                                srdRunway = line[3]

                                # for each SID, get the route
                                routeSearch = re.findall(rf'^({line[1]})\s+([\dA-Z]{{3,5}})', data, re.M)

                                if routeSearch:
                                    concatRoute = ''
                                    for route in routeSearch:
                                        concatRoute += route[1] + "/"
                                        routeName = route[0]

                                    if line[4]:
                                        starRunways = line[4].split(',')
                                        for rwy in starRunways:
                                            dfOut = {'ICAO': icao, 'Runway': rwy, 'Name': routeName, 'Route': concatRoute.rstrip('/')}
                                            df = df.append(dfOut, ignore_index=True)

                                    dfOut = {'ICAO': icao, 'Runway': srdRunway, 'Name': routeName, 'Route': concatRoute.rstrip('/')}
                                    df = df.append(dfOut, ignore_index=True)

            return df[(df.Runway == rwyIn)]

class ValidateXml:
    """docstring for ValidateXml."""

    def __init__(self, schema):
        with open(schema) as sFile:
            self.schema = xmlschema.XMLSchema(sFile)

    def validateDir(self, searchDir, matchFile):
        with alive_bar() as bar:
            for subdir, dirs, files in os.walk(searchDir):
                for filename in files:
                    filepath = subdir + os.sep + filename
                    if fnmatch.fnmatch(filename, matchFile + '.xml'):
                        bar()
                        if self.schema.is_valid(filepath) is False:
                            self.schema.validate(filepath)

        print(Fore.GREEN + "OK" + Style.RESET_ALL + " - All tests passed for " + searchDir + matchFile)

def mysqlExec(sql, sqlType):
    try:
        if sqlType == "insertUpdate":
            cursor.execute(sql)
            mysqlconnect.db.commit()
        elif sqlType == "selectOne":
            cursor.execute(sql)
            return cursor.fetchone()
        elif sqlType == "selectMany":
            cursor.execute(sql)
            return cursor.fetchall()
    except mysql.connector.Error as err:
        print(err)

# Main Menu
print("")
print("##############################")
print("# vatSys XML Builder v0.1b   #")
print("##############################")
print("")
print("(1) - Perform a webscrape to obtain current AIRAC data.")
print("(2) - Build XML files from the existing database.")
print("(3) - Truncate the existing database.")
print("(4) - Convert a Google Earth KML file - run with -g option to pass KML filename.")
print("(5) - Convert EuroScope files.")
print("(6) - Validate XML files.")
print("")
menuOption = input("Please select an option: ")

if menuOption == '1':
    print("By default, this will webscrape the eAIP for the United Kingdom (EGxx).")
    print("Default []")
    print("Please enter a different base URL if required or press enter to continue: ")
    Profile.clearDatabase() # wipe the database first # BUG: need to code a database backup here first just in case...
    WebScrape.processAd06Data()
    #WebScrape.parseUKMil() # placeholder
    WebScrape.main()
    WebScrape.firUirTmaCtaData()
    WebScrape.parseENR3("1")
    WebScrape.parseENR3("3")
    WebScrape.parseENR3("5")
elif menuOption == '2':
    Profile.constructXml()
    Profile.createFrequencies()
    Profile.createRadars()
elif menuOption == '3':
    Profile.clearDatabase()
elif menuOption == '4':
    Geo.kmlMappingConvert(args.geo)
elif menuOption == '5':
    print("Not Defined")
elif menuOption == '6':
    twrMap = ValidateXml("Validation/twrmap.xsd")
    twrMap.validateDir("Build/Maps", "*TWR*")
    airspace = ValidateXml("Validation/airspace.xsd")
    airspace.validateDir("Build", "Airspace")
elif menuOption == '9':
    #Profile.createFrequencies()
    #WebScrape.firUirTmaCtaData()
    sids = Navigraph.sidStar("sids.txt", "EGKK", "26L")
    print(sids.head)

    for s in sids['Route']:
        print(s)
else:
    print("Nothing to do here\n")
    cmdParse.print_help()
