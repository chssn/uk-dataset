#! /usr/bin/python3
import sys
import requests
import re
import prettierfier as pretty
import xml.etree.ElementTree as xtree
import urllib3
import mysql.connector
import mysqlconnect ## mysql connection details
from datetime import datetime
from bs4 import BeautifulSoup
from colorama import Fore, Back, Style
from time import time, ctime
from alive_progress import alive_bar

### This file generates the Airspace.xml file for VATSys from the UK NATS AIRAC

cursor = mysqlconnect.db.cursor()

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

def plusMinus(arg):
    if arg == "N" or arg == "E":
        return "+"
    elif arg == "S" or arg == "W":
        return "-"

class Profile():
    def constructXml():    ## Define XML top level tag
        xmlAirspace = xmlRoot('Airspace')
        now = datetime.now()
        checkID = datetime.timestamp(now) ## generate unix timestamp to help verify if a row has already been added
        ## Define subtag SystemRunways - https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
        xmlSystemRunways = xtree.SubElement(xmlAirspace, 'SystemRunways')
        xmlSidStar = xtree.SubElement(xmlAirspace, 'SIDSTARs')
        xmlIntersections = xtree.SubElement(xmlAirspace, 'Intersections')
        xmlAirports = xtree.SubElement(xmlAirspace, 'Airports')

        ## Construct the XML element as per https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
        ## List all the verified aerodromes
        sql = "SELECT * FROM aerodromes WHERE verified = '1' AND icao_designator = 'EGKK'"
        #sql = "SELECT * FROM aerodromes WHERE verified = '1'"
        listAerodromes = mysqlExec(sql, "selectMany")
        for aerodrome in listAerodromes:
            ## Set airport name
            xmlAerodrome = xtree.SubElement(xmlSystemRunways, 'Airport')
            xmlAerodrome.set('Name', aerodrome[1])
            print(Fore.BLUE + "Constructing XML for " + aerodrome[1] + " ("+ str(aerodrome[0]) +")" + Style.RESET_ALL)
            xmlAirport = xtree.SubElement(xmlAirports, 'Airport')
            xmlAirport.set('ICAO', aerodrome[1])
            xmlAirport.set('Position', aerodrome[3])
            xmlAirport.set('Elevation', str(aerodrome[4]))

            ## Now for the runways that form part of the aerodrome
            sqlA = "SELECT * FROM aerodrome_runways WHERE aerodrome_id = '"+ str(aerodrome[0]) +"'"
            listRunways = mysqlExec(sqlA, "selectMany")
            for runway in listRunways:
                xmlRunway = xtree.SubElement(xmlAerodrome, 'Runway')
                xmlRunway.set('Name', runway[2])
                xmlRunway.set('DataRunway', runway[2])
                print("-- Constructing XML for runway " + runway[2])

                ## Now the SIDs for that runway
                sqlB = "SELECT * FROM aerodrome_runways_sid WHERE runway_id = '"+ str(runway[0]) +"' AND buildcheck != '"+ str(checkID) +"'"
                try:
                    listSids = mysqlExec(sqlB, "selectMany")
                    for sid in listSids:
                        xmlSid = xtree.SubElement(xmlRunway, 'SID')
                        xmlSid.set('Name', sid[2])
                        print("---- Constructing XML for SID " + sid[2])

                        ## Build in the extra bits for the SIDSTARs section - https://virtualairtrafficsystem.com/docs/dpk/#sidstars
                        ## Check to see if multiple runways are using the same SID
                        sqlC = "SELECT aerodrome_runways.runway, aerodrome_runways_sid.id FROM aerodrome_runways INNER JOIN aerodrome_runways_sid ON aerodrome_runways.id = aerodrome_runways_sid.runway_id WHERE aerodrome_runways_sid.sid = '"+ sid[2] +"' AND buildcheck != '"+ str(checkID) +"'"
                        runwaySid = mysqlExec(sqlC, "selectMany")
                        runwaySelect = ''
                        xmlSidStarSid = xtree.SubElement(xmlSidStar, 'SID')

                        for rS in runwaySid:
                            xmlRoute = xtree.SubElement(xmlSidStarSid, 'Route')
                            xmlRoute.set('Runway', str(rS[0]))
                            xmlRoute.text = sid[3]
                            runwaySelect += str(rS[0])
                            print("------ Constructing XML for SID " + sid[2] + " on runway " + str(rS[0]))

                            ## update the database SID entry with the checkID
                            sqlU = "UPDATE aerodrome_runways_sid SET buildcheck = '"+ str(checkID) +"' WHERE id = '"+ str(rS[1]) +"'"
                            mysqlExec(sqlU, "insertUpdate")

                        xmlSidStarSid.set('Name', sid[2])
                        xmlSidStarSid.set('Airport', aerodrome[1])
                        xmlSidStarSid.set('Runways', runwaySelect)

                        #xmlTransition = xtree.SubElement(xmlSidStarSid, 'Transition')
                        #trans = sid[3].split() ## get the start of the STAR route
                        #xmlTransition.set('Name', trans[0]) # BUG: Don't think this is the correct bit for the transition
                        #xmlTransition.text = trans[0] # BUG: Same as line above
                except mysql.connector.Error as err:
                    print(err)

                ## Now the STARs for that runway
                sqlD = "SELECT * FROM aerodrome_runways_star WHERE runway_id = '"+ str(runway[0]) +"'"
                try:
                    listStars = mysqlExec(sqlD, "selectMany")
                    for star in listStars:
                        xmlStar = xtree.SubElement(xmlRunway, 'STAR')
                        xmlStar.set('Name', star[2])
                        print("---- Constructing XML for STAR " + star[2])

                        ## Build in the extra bits for the SIDSTARs section - https://virtualairtrafficsystem.com/docs/dpk/#sidstars
                        xmlSidStarStar = xtree.SubElement(xmlSidStar, 'STAR')
                        xmlSidStarStar.set('Name', star[2])
                        xmlSidStarStar.set('Airport', aerodrome[1])
                        xmlSidStarStar.set('Runways', runway[2])

                        #xmlTransition = xtree.SubElement(xmlSidStarStar, 'Transition')
                        #trans = star[3].split() ## get the start of the STAR route
                        #xmlTransition.set('Name', trans[0]) # BUG: Don't think this is the correct bit for the transition
                        #xmlTransition.text = trans[0] # BUG: Same as line above

                        xmlRoute = xtree.SubElement(xmlSidStarStar, 'Route')
                        xmlRoute.set('Runway', runway[2])
                        xmlRoute.text = star[3]
                except:
                    pass

        ## Construct the XML element as per https://virtualairtrafficsystem.com/docs/dpk/#intersections
        ## List all the verified points
        sql = "SELECT * FROM fixes"
        listFixes = mysqlExec(sql, "selectMany")
        for fix in listFixes:
            xmlFix = xtree.SubElement(xmlIntersections, 'Point')
            xmlFix.set('Name', fix[1])
            xmlFix.set('Type', 'Fix')
            xmlFix.text = fix[2]

        sql = "SELECT * FROM navaids"
        listNavAids = mysqlExec(sql, "selectMany")
        for fix in listNavAids:
            xmlFix = xtree.SubElement(xmlIntersections, 'Point')
            xmlFix.set('Name', fix[1])
            xmlFix.set('Type', 'Navaid')
            xmlFix.set('NavaidType', fix[2])
            xmlFix.text = fix[3]

        tree = xtree.ElementTree(xmlAirspace)
        tree.write('Airspace.xml', encoding="utf-8", xml_declaration=True)
    # BUG: Probably read the whole XML through and run this regex (Runways=")([0-9]{2}[L|R|C]?)([0-9]{2}[L|R|C]?)(") and replace $1$2,$3$4
    def clearDatabase():
        print(Fore.RED + "!!!WARNING!!!" + Style.RESET_ALL)
        print("This will truncate (delete) the contents of all tables in this database.")
        print("Are you sure you wish to contine?")
        print("Please type 'confirm' to continue or any other option to leave the database intact: ")
        confirmation = input()
        if confirmation == "confirm":
            ## Back everything up first!
            sqlA = "BACKUP DATABASE uk-dataset TO DISK 'backup.sql'"
            sqlB = "TRUNCATE TABLE aerodromes"
            sqlC = "TRUNCATE TABLE aerodrome_runways"
            sqlD = "TRUNCATE TABLE aerodrome_runways_sid"
            sqlE = "TRUNCATE TABLE aerodrome_runways_star"
            sqlF = "TRUNCATE TABLE fixes"
            sqlG = "TRUNCATE TABLE navaids"
            #cursor.execute(sqlA)
            cursor.execute(sqlB)
            cursor.execute(sqlC)
            cursor.execute(sqlD)
            cursor.execute(sqlE)
            cursor.execute(sqlF)
            cursor.execute(sqlG)
        else:
            print("No data has been deleted. We think...")

    def processAd06Data():
        print("Processing EG-AD-0.6 data to obtain ICAO designators...")
        getAerodromeList = getAiracTable("EG-AD-0.6-en-GB.html")
        listAerodromeList = getAerodromeList.find_all("tr") # IDEA: Think there is a more efficient way of parsing this data
        for row in listAerodromeList:
            getAerodrome = row.find(string=re.compile("^(EG)[A-Z]{2}$"))
            if getAerodrome is not None:
                ## Place each aerodrome into the DB
                sql = "INSERT INTO aerodromes (icao_designator, verified, location, elevation) VALUES ('"+ getAerodrome +"' , 0, 0, 0)"
                mysqlExec(sql, "insertUpdate")  ## Process data from AD 0.6

Profile.constructXml()
exit()
## Truncate all tables in the database. After all, this should only be run once per AIRAC cycle...
Profile.clearDatabase()
## Get AD2 aerodrome list from AD0.6 table
Profile.processAd06Data()

## Count the number of ICAO designators (may not actually be a verified aerodrome)
sql = "SELECT COUNT(icao_designator) AS NumberofAerodromes FROM aerodromes"
numberofAerodromes = mysqlExec(sql, "selectOne")

with alive_bar(numberofAerodromes[0]) as bar: ## Define the progress bar
    ## Select all aerodromes and loop through
    sql = "SELECT id, icao_designator FROM aerodromes"
    tableAerodrome = mysqlExec(sql, "selectMany")

    for aerodrome in tableAerodrome:    ## AD 2 data
        ## list all aerodrome runways
        bar() # progress the progress bar
        getRunways = getAiracTable("EG-AD-2."+ aerodrome[1] +"-en-GB.html") ## Try and find all information for this aerodrome
        if getRunways != 404:
            ## Add verify flag for this aerodrome
            sql = "UPDATE aerodromes SET verified = 1 WHERE id = '"+ str(aerodrome[0]) +"'"
            mysqlExec(sql, "insertUpdate")

            print("Processing EG-AD-2 Data for "+ aerodrome[1] +"...")
            aerodromeLocation = getRunways.find(id=aerodrome[1] + "-AD-2.2")
            aerodromeRunways = getRunways.find(id=aerodrome[1] + "-AD-2.12")

            for rwy in aerodromeRunways:
                addRunway = rwy.find_all(string=re.compile("(RWY)\s[0-3]{1}[0-9]{1}[L|R|C]?$")) ## String to search for runway designations
                for a in addRunway:
                    if a is not None:
                        rwyDes = a.split()
                        ## Add runway to the aerodromeDB
                        sql = "INSERT INTO aerodrome_runways (aerodrome_id, runway) SELECT * FROM (SELECT '"+ str(aerodrome[0]) +"' AS airid, '"+ str(rwyDes[1]) +"' AS rwy) AS tmp WHERE NOT EXISTS (SELECT aerodrome_id FROM aerodrome_runways WHERE aerodrome_id =  '"+ str(aerodrome[0]) +"' AND runway = '"+ str(rwyDes[1]) +"') LIMIT 1"
                        mysqlExec(sql, "insertUpdate")

            #for loc in aerodromeLocation:
            aerodromeLat = re.search('(Lat: )(<span class="SD" id="ID_[0-9]{7}">)([0-9]{6})([N|S]{1})', str(aerodromeLocation))
            aerodromeLon = re.search(r"(Long: )(<span class=\"SD\" id=\"ID_[0-9]{7}\">)([0-9]{7})([E|W]{1})", str(aerodromeLocation))
            aerodromeElev = re.search(r"(VAL_ELEV\;)([0-9]{1,4})", str(aerodromeLocation))

            if aerodromeLat:
                latPM = plusMinus(aerodromeLat.group(4))
            else:
                latPM = "+" # BUG: lazy fail option

            if aerodromeLon:
                lonPM = plusMinus(aerodromeLon.group(4))
            else:
                lonPM = "-" # BUG: Lazy fail option

            fullLocation = latPM + aerodromeLat.group(3) + lonPM + aerodromeLon.group(3)

            sql = "UPDATE aerodromes SET location = '"+ str(fullLocation) +"', elevation = '"+ aerodromeElev[2] +"' WHERE id = '"+ str(aerodrome[0]) +"'"
            mysqlExec(sql, "insertUpdate")
        else:
            ## Remove verify flag for this aerodrome
            sql = "UPDATE aerodromes SET verified = 0 WHERE id = '"+ str(aerodrome[0]) +"'"
            mysqlExec(sql, "insertUpdate")
            print(Fore.RED + "Aerodrome " + aerodrome[1] + " does not exist" + Style.RESET_ALL)

##########################################################################################################
## Define the XML sub tag 'Intersections' - https://virtualairtrafficsystem.com/docs/dpk/#intersections ##
##########################################################################################################
    ## Get ENR-4.1 data from the defined website
    print("Processing EG-ENR-4.1 Data (RADIO NAVIGATION AIDS - EN-ROUTE)...")
    getENR41 = getAiracTable("EG-ENR-4.1-en-GB.html")
    listENR41 = getENR41.find_all("tr", class_ = "Table-row-type-3")
    enr41(listENR41)
    bar() # progress the progress bar

    ## Get ENR-4.4 data from the defined website
    print("Processing EG-ENR-4.4 Data (NAME-CODE DESIGNATORS FOR SIGNIFICANT POINTS)...")
    getENR44 = getAiracTable("EG-ENR-4.4-en-GB.html")
    listENR44 = getENR44.find_all("tr", class_ = "Table-row-type-3")
    enr44(listENR44)
    bar() # progress the progress bar

##########################################################################################################
## Define the XML sub tag 'SIDSTARs' - https://virtualairtrafficsystem.com/docs/dpk/#sidstars           ##
##########################################################################################################
# IDEA: This is currently scraping the *.ese file from VATSIM-UK. Need to find a better way of doing this. Too much hard code here and it's lazy!
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
                except:
                    print(Fore.RED + "Aerodrome ICAO " + aerodrome + " not recognised" + Style.RESET_ALL)
                    print(line)

            bar() # progress the progress bar

    Profile.constructXml()
