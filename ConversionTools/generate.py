#!/usr/bin/env python3
import math
import datetime
import urllib3
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
from datetime import date
from defusedxml import defuse_stdlib
from bs4 import BeautifulSoup
from colorama import Fore, Style
from time import time, ctime
from alive_progress import alive_bar
from pykml import parser
from shapely.geometry import MultiPoint

cursor = mysqlconnect.db.cursor()

def mysqlExec(sql, sqlType):
    try:
        if sqlType == "insert":
            cursor.execute(sql)
            mysqlconnect.db.commit()
        elif sqlType == "one":
            cursor.execute(sql)
            return cursor.fetchone()
        elif sqlType == "all":
            cursor.execute(sql)
            return cursor.fetchall()
    except mysql.connector.Error as err:
        print(err)

class Database:
    '''Class for database functions NOT WORKING'''

    def __init__(self):
        self.cursor = mysqlconnect.db.cursor()

    def insert(self, sql):
        self.cursor.execute(sql)
        mysqlconnect.db.commit()

    def selectOne(self, sql):
        self.cursor.execute(sql)
        return self.cursor.fetchone()

    def selectAll(self, sql):
        self.cursor.execute(sql)
        return self.cursor.fetchall()

    def exec(self, sql, action):
        try:
            if action == "insert":
                self.insert(sql)
            elif action == "one":
                self.selectOne(sql)
            elif action == "all":
                self.selectAll(sql)
        except mysql.connector.Error as err:
            print(err)

    def close(self):
        self.cursor.close()

    def clear():
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

class Airac:
    '''Class for general functions relating to AIRAC'''

    def __init__(self):
        # First AIRAC date following the last cycle length modification
        startDate = "2019-01-02"
        self.baseDate = date.fromisoformat(str(startDate))
        # Length of one AIRAC cycle
        self.cycleDays = 28

    def initialise(self, dateIn=0):
        # Calculate the number of AIRAC cycles between any given date and the start date
        if dateIn:
            inputDate = date.fromisoformat(str(dateIn))
        else:
            inputDate = date.today()

        # How many AIRAC cycles have occured since the start date
        diffCycles = (inputDate - self.baseDate) / datetime.timedelta(days=1)
        # Round that number down to the nearest whole integer
        numberOfCycles = math.floor(diffCycles / self.cycleDays)

        return numberOfCycles

    def currentCycle(self):
        # Return the date of the current AIRAC cycle
        numberOfCycles = self.initialise()
        numberOfDays = numberOfCycles * self.cycleDays + 1
        return self.baseDate + datetime.timedelta(days=numberOfDays)

    def nextCycle(self):
        # Return the date of the next AIRAC cycle
        numberOfCycles = self.initialise()
        numberOfDays = (numberOfCycles + 1) * self.cycleDays + 1
        return self.baseDate + datetime.timedelta(days=numberOfDays)

    def url(self, next=0):
        # Return a generated URL based on the AIRAC cycle start date
        baseUrl = "https://www.aurora.nats.co.uk/htmlAIP/Publications/"
        if next:
            baseDate = self.nextCycle() # if the 'next' variable is passed, generate a URL for the next AIRAC cycle
        else:
            baseDate = self.currentCycle()

        basePostString = "-AIRAC/html/eAIP/"
        return baseUrl + str(baseDate) + basePostString

class Webscrape:
    '''Class to scrape data from the given AIRAC eAIP URL'''

    def __init__(self, next=0):
        cycle = Airac()
        self.cycleUrl = cycle.url()
        self.country = "EG"
        self.database = Database()

    def getTableSoup(self, uri):
        # Parse the given table into a beautifulsoup object
        address = self.cycleUrl + uri

        http = urllib3.PoolManager()
        error = http.request("GET", address)
        if (error.status == 404):
            return 404

        page = requests.get(address)
        return BeautifulSoup(page.content, "lxml")

    def parseAd01Data(self):
        dfColumns = ['icao_designator','verified','location','elevation','name','magnetic_variation']
        df = pd.DataFrame(columns=dfColumns)

        print("Parsing "+ self.country +"-AD-0.1 data to obtain ICAO designators...")
        getAerodromeList = self.getTableSoup(self.country + "-AD-0.1-en-GB.html")
        listAerodromeList = getAerodromeList.find_all("h3")
        barLength = len(listAerodromeList)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in listAerodromeList:
                getAerodrome = re.search(rf"({self.country}[A-Z]{{2}})(\n[\s\S]{{7}}\n[\s\S]{{8}})([A-Z]{{4}}.*)(\n[\s\S]{{6}}<\/a>)", str(row)) # search for aerodrome icao designator and name
                if getAerodrome:
                    # Place each aerodrome into the DB
                    #sql = "INSERT INTO aerodromes (icao_designator, verified, location, elevation, name) VALUES ('"+ str(getAerodrome[1]) +"' , 0, 0, 0, '"+ str(getAerodrome[3]) +"')"
                    #mysqlExec(sql, "insert")

                    dfOut = {'icao_designator': str(getAerodrome[1]),'verified': 0,'location': 0,'elevation': 0,'name': str(getAerodrome[3]),'magnetic_variation': 0}
                    df = df.append(dfOut, ignore_index=True)
                bar()
        return df

    def parseAd02Data(self, dfAd01):
        print("Parsing "+ self.country +"-AD-2.x data to obtain aerodrome data...")

        # Select all aerodromes in the database
        #sql = "SELECT id, icao_designator FROM aerodromes ORDER BY icao_designator"
        #getAerodromes = mysqlExec(sql, "all")
        barLength = len(dfAd01.index)
        with alive_bar(barLength) as bar: # Define the progress bar
            for aerodrome in getAerodromes:
                aeroId = aerodrome[0]
                aeroIcao = aerodrome[1]
                # Select all runways in this aerodrome
                getRunways = self.getTableSoup(self.country + "-AD-2."+ aeroIcao +"-en-GB.html")
                if getRunways !=404:
                    print("  Parsing AD-2 data for " + aeroIcao)
                    aerodromeAd0202 = getRunways.find(id=aerodrome[1] + "-AD-2.2")
                    aerodromeAd0212 = getRunways.find(id=aerodrome[1] + "-AD-2.12")
                    aerodromeAd0218 = getRunways.find(id=aerodrome[1] + "-AD-2.18")

                    # Find current magnetic variation for this aerodrome
                    aerodromeMagVar = self.search("([\d]{1}\.[\d]{2}).([W|E]{1})", "TAD_HP;VAL_MAG_VAR", str(aerodromeAd0202))
                    pM = Geo.plusMinus(aerodromeMagVar[0][1])
                    floatMagVar = pM + aerodromeMagVar[0][0]

                    # Add verified flag and magnetic variation for this aerodrome
                    sql = "UPDATE aerodromes SET verified = 1, magnetic_variation = '"+ str(floatMagVar) +"' WHERE id = '"+ str(aeroId) +"'"
                    mysqlExec(sql, "insert")

                    # Find lat/lon/elev for aerodrome
                    aerodromeLat = re.search(r'(Lat: )(<span class="SD" id="ID_[\d]{7}">)([\d]{6})([N|S]{1})', str(aerodromeAd0202))
                    aerodromeLon = re.search(r"(Long: )(<span class=\"SD\" id=\"ID_[\d]{7}\">)([\d]{7})([E|W]{1})", str(aerodromeAd0202))
                    aerodromeElev = re.search(r"(VAL_ELEV\;)([\d]{1,4})", str(aerodromeAd0202))

                    latPM = Geo.plusMinus(aerodromeLat.group(4))
                    lonPM = Geo.plusMinus(aerodromeLon.group(4))
                    fullLocation = latPM + aerodromeLat.group(3) + ".00" + lonPM + aerodromeLon.group(3) + ".00" # AD-2.2 gives aerodrome location as DDMMSS / DDDMMSS

                    sql = "UPDATE aerodromes SET location = '"+ str(fullLocation) +"', elevation = '"+ aerodromeElev[2] +"' WHERE id = '"+ str(aeroId) +"'"
                    mysqlExec(sql, "insert")

                    # Find runway locations
                    aerodromeRunways = self.search("([\d]{2}[L|C|R]?)", "TRWY_DIRECTION;TXT_DESIG", str(aerodromeAd0212))
                    aerodromeRunwaysLat = self.search("([\d]{6}\.[\d]{2}[N|S]{1})", "TRWY_CLINE_POINT;GEO_LAT", str(aerodromeAd0212))
                    aerodromeRunwaysLong = self.search("([\d]{7}\.[\d]{2}[E|W]{1})", "TRWY_CLINE_POINT;GEO_LONG", str(aerodromeAd0212))
                    aerodromeRunwaysElev = self.search("([\d]{3})", "TRWY_CLINE_POINT;VAL_GEOID_UNDULATION", str(aerodromeAd0212))
                    aerodromeRunwaysBearing = self.search("([\d]{3}\.[\d]{2}.)", "TRWY_DIRECTION;VAL_TRUE_BRG", str(aerodromeAd0212))
                    aerodromeRunwaysLen = self.search("([\d]{3,4})", "TRWY;VAL_LEN", str(aerodromeAd0212))

                    for rwy, lat, lon, elev, brg, rwyLen in zip(aerodromeRunways, aerodromeRunwaysLat, aerodromeRunwaysLong, aerodromeRunwaysElev, aerodromeRunwaysBearing, aerodromeRunwaysLen):
                        # Add runway to the aerodromeDB
                        latSplit = re.search(r"([\d]{6}\.[\d]{2})([N|S]{1})", str(lat))
                        lonSplit = re.search(r"([\d]{7}\.[\d]{2})([E|W]{1})", str(lon))
                        latPM = Geo.plusMinus(latSplit.group(2))
                        lonPM = Geo.plusMinus(lonSplit.group(2))
                        loc = str(latPM) + str(latSplit.group(1)) + str(lonPM) + str(lonSplit.group(1)) # build lat/lon string as per https://virtualairtrafficsystem.com/docs/dpk/#lat-long-format

                        sql = "INSERT INTO aerodrome_runways (aerodrome_id, runway, location, elevation, bearing, length) VALUE ('"+ str(aeroId) +"', '"+ str(rwy) +"', '"+ str(loc) +"', '"+ str(elev) +"', '"+ str(brg.rstrip('°')) +"', '"+ str(rwyLen) +"')"
                        mysqlExec(sql, "insert")

                    # Find air traffic services
                    aerodromeServices = self.search("(APPROACH|GROUND|DELIVERY|TOWER|DIRECTOR|INFORMATION)", "TCALLSIGN_DETAIL", str(aerodromeAd0218))
                    serviceFrequency = self.search("([\d]{3}\.[\d]{3})", "TFREQUENCY", str(aerodromeAd0218))

                    for srv, frq in zip(aerodromeServices, serviceFrequency):
                        callSignId = "SELECT id FROM standard_callsigns WHERE description = '"+ str(srv) +"' LIMIT 1"
                        callSignType = mysqlExec(callSignId, "one")
                        csModify = re.search(r"([\d]{1,8})", str(callSignType))

                        sql = "INSERT INTO aerodrome_frequencies (aerodrome_id, callsign_type_id, frequency) VALUE ('"+ str(aeroId) +"', '"+ str(csModify.group(1)) +"', '"+ str(frq) +"')"
                        mysqlExec(sql, "insert")
                else:
                    # Remove verify flag for this aerodrome
                    sql = "UPDATE aerodromes SET verified = 0 WHERE id = '"+ str(aerodrome[0]) +"'"
                    mysqlExec(sql, "insert")
                    print(Fore.RED + "Aerodrome " + aerodrome[1] + " does not exist" + Style.RESET_ALL)
                bar()

    def parseEnr02Data(self):
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

        print("Parsing "+ self.country +"-ENR-2.1 Data (FIR, UIR, TMA AND CTA)...")
        getData = self.getTableSoup(self.country + "-ENR-2.1-en-GB.html")
        searchData = getData.find_all("td")
        barLength = len(searchData)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in searchData:
                # find all FIR spaces
                firTitle = self.search("([A-Z]*\sFIR)", "TAIRSPACE;TXT_NAME", str(row))
                firSpace = self.search("([\d]{6,7})([N|E|S|W]{1})", "TAIRSPACE_VERTEX;GEO_L", str(row))
                firUpper = self.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_LAYER;VAL_DIST_VER_UPPER", str(row))
                firLower = self.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_LAYER;VAL_DIST_VER_LOWER", str(row))
                if not firUpper:
                    firUpper = self.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_VOLUME;VAL_DIST_VER_UPPER", str(row))
                    firLower = self.search("(?<=\>)([\d]{2,3})", "TAIRSPACE_VOLUME;VAL_DIST_VER_LOWER", str(row))
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
                ctaTitle = self.search("([A-Z\s]*)(\sCTA\s)([\d]?)", "TAIRSPACE;TXT_NAME", str(row))
                ctaSpace = self.search("([\d]{6,7})([N|E|S|W]{1})", "TAIRSPACE_VERTEX;GEO_L", str(row))
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
                tmaTitle = self.search("([A-Z\s]*)(\sTMA\s)([\d]?)", "TAIRSPACE;TXT_NAME", str(row))
                tmaSpace = self.search("([\d]{6,7})([N|E|S|W]{1})", "TAIRSPACE_VERTEX;GEO_L", str(row))
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

    def parseEnr03Data(self, section):
        print("Parsing "+ self.country +"-ENR-3."+ section +" data to obtain ATS routes...")
        getENR3 = self.getTableSoup(self.country + "-ENR-3."+ section +"-en-GB.html")
        listTables = getENR3.find_all("tbody")
        barLength = len(listTables)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in listTables:
                getAirwayName = self.search("([A-Z]{1,2}[\d]{1,4})", "TEN_ROUTE_RTE;TXT_DESIG", str(row))
                getAirwayRoute = self.search("([A-Z]{3,5})", "T(DESIGNATED_POINT|DME|VOR|NDB);CODE_ID", str(row))
                printRoute = ''
                if getAirwayName:
                    for point in getAirwayRoute:
                        printRoute += str(point[0]) + "/"
                    sql = "INSERT INTO airways (name, route) VALUES ('"+ str(getAirwayName[0]) +"', '"+ str(printRoute).rstrip('/') +"')"
                    mysqlExec(sql, "insertUpdate")
                bar()

    def parseEnr04Data(self, sub):
        print("Parsing "+ self.country +"-ENR-4."+ sub +" Data (RADIO NAVIGATION AIDS - EN-ROUTE)...")
        getData = self.getTableSoup(self.country + "-ENR-4."+ sub +"-en-GB.html")
        listData = getData.find_all("tr", class_ = "Table-row-type-3")
        barLength = len(listData)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in listData:
                # Split out the point name
                id = row['id']
                name = id.split('-')

                # Find the point location
                pointLat = self.search(r"([\d]{6})([N|S]{1})", "T", str(row))
                pointLon = self.search(r"([\d]{7})([E|W]{1})", "T", str(row))
                latPM = Geo.plusMinus(pointLat[0][1])
                lonPM = Geo.plusMinus(pointLon[0][1])
                fullLocation = latPM + pointLat[0][0] + ".00" + lonPM + pointLon[0][0] + ".00" # ENR-4 gives aerodrome location as DDMMSS / DDDMMSS

                if sub == "1":
                    # Do this for ENR-4.1
                    # Set the navaid type correctly
                    if name[1] == "VORDME":
                        name[1] = "VOR"
                    #elif name[1] == "DME": # prob don't need to add all the DME points in this area
                    #    name[1] = "VOR"

                    # Add navaid to the aerodromeDB
                    sql = "INSERT INTO navaids (name, type, coords) SELECT * FROM (SELECT '"+ str(name[2]) +"' AS srcName, '"+ str(name[1]) +"' AS srcType, '"+ str(fullLocation) +"' AS srcCoord) AS tmp WHERE NOT EXISTS (SELECT name FROM navaids WHERE name =  '"+ str(name[2]) +"' AND type =  '"+ str(name[1]) +"' AND coords = '"+ str(fullLocation) +"') LIMIT 1"
                    mysqlExec(sql, "insert")
                elif sub == "4":
                    # Add fix to the aerodromeDB
                    sql = "INSERT INTO fixes (name, coords) SELECT * FROM (SELECT '"+ str(name[1]) +"' AS srcName, '"+ str(fullLocation) +"' AS srcCoord) AS tmp WHERE NOT EXISTS (SELECT name FROM fixes WHERE name =  '"+ str(name[1]) +"' AND coords = '"+ str(fullLocation) +"') LIMIT 1"
                    mysqlExec(sql, "insert")
                bar()

    def run(self):
        #Database.clear()
        dataA = self.parseAd01Data()
        self.parseAd02Data(dataA)
        #self.parseEnr02Data()
        #self.parseEnr03Data('1')
        #self.parseEnr03Data('3')
        #self.parseEnr03Data('5')
        #self.parseEnr04Data('1')
        #self.parseEnr04Data('4')

    @staticmethod
    def search(find, name, string):
        searchString = find + "(?=<\/span>.*>" + name + ")"
        result = re.findall(rf"{str(searchString)}", str(string))
        return result

class Geo:
    '''Class to store various geo tools'''

    @staticmethod
    def plusMinus(arg): # Turns a compass point into the correct + or - for lat and long
        if arg in ('N','E'):
            return "+"
        return "-"

    @staticmethod
    def backBearing(brg):
        if (float(brg) - 180) < 0:
            bB = float(brg) + 180.00
        else:
            bB = float(brg) - 180.00
        return round(bB, 2)

    @staticmethod
    def kmlMappingConvert(fileIn, icao): # BUG: needs reworking
        def mapLabels():
            # code to generate the map labels.
            points = MultiPoint(latLonString) # function to calculate polygon centroid
            labelPoint = points.centroid
            labelPrint = re.sub(r'[A-Z()]', '', str(labelPoint))
            labelSplit = labelPrint.split()

            xmlGroundMapInfLabelPoint = xtree.SubElement(xmlGroundMapInfLabel, 'Point')
            xmlGroundMapInfLabelPoint.set('Name', splitName[1])
            xmlGroundMapInfLabelPoint.text = "+" + str(labelSplit[0]) + re.sub(r'-0\.', '-000.', labelSplit[1])

        aerodromeIcao = icao

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

# Defuse XML
defuse_stdlib()
new = Webscrape()
new.run()
