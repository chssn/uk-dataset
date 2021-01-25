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
import xmlschema
from datetime import date
from defusedxml import defuse_stdlib
from bs4 import BeautifulSoup
from colorama import Fore, Style
from time import time, ctime
from alive_progress import alive_bar
from pykml import parser
from shapely.geometry import MultiPoint

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
        print("Parsing "+ self.country +"-AD-0.1 data to obtain ICAO designators...")
        dfColumns = ['icao_designator','verified','location','elevation','name','magnetic_variation']
        df = pd.DataFrame(columns=dfColumns)
        getAerodromeList = self.getTableSoup(self.country + "-AD-0.1-en-GB.html")
        listAerodromeList = getAerodromeList.find_all("h3")
        barLength = len(listAerodromeList)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in listAerodromeList:
                getAerodrome = re.search(rf"({self.country}[A-Z]{{2}})(\n[\s\S]{{7}}\n[\s\S]{{8}})([A-Z]{{4}}.*)(\n[\s\S]{{6}}<\/a>)", str(row)) # search for aerodrome icao designator and name
                if getAerodrome:
                    # Place each aerodrome into the DB
                    dfOut = {'icao_designator': str(getAerodrome[1]),'verified': 0,'location': 0,'elevation': 0,'name': str(getAerodrome[3]),'magnetic_variation': 0}
                    df = df.append(dfOut, ignore_index=True)
                bar()
        return df

    def parseAd02Data(self, dfAd01):
        print("Parsing "+ self.country +"-AD-2.x data to obtain aerodrome data...")
        dfColumns = ['icao_designator','runway','location','elevation','bearing','length']
        dfRwy = pd.DataFrame(columns=dfColumns)

        dfColumns = ['icao_designator','callsign_type','frequency']
        dfSrv = pd.DataFrame(columns=dfColumns)

        # Select all aerodromes in the database
        barLength = len(dfAd01.index)
        with alive_bar(barLength) as bar: # Define the progress bar
            for index, row in dfAd01.iterrows():
                aeroIcao = row['icao_designator']
                # Select all runways in this aerodrome
                getRunways = self.getTableSoup(self.country + "-AD-2."+ aeroIcao +"-en-GB.html")
                if getRunways !=404:
                    print("  Parsing AD-2 data for " + aeroIcao)
                    aerodromeAd0202 = getRunways.find(id=aeroIcao + "-AD-2.2")
                    aerodromeAd0212 = getRunways.find(id=aeroIcao + "-AD-2.12")
                    aerodromeAd0218 = getRunways.find(id=aeroIcao + "-AD-2.18")

                    # Find current magnetic variation for this aerodrome
                    aerodromeMagVar = self.search("([\d]{1}\.[\d]{2}).([W|E]{1})", "TAD_HP;VAL_MAG_VAR", str(aerodromeAd0202))
                    pM = Geo.plusMinus(aerodromeMagVar[0][1])
                    floatMagVar = pM + aerodromeMagVar[0][0]

                    # Find lat/lon/elev for aerodrome
                    aerodromeLat = re.search(r'(Lat: )(<span class="SD" id="ID_[\d]{7}">)([\d]{6})([N|S]{1})', str(aerodromeAd0202))
                    aerodromeLon = re.search(r"(Long: )(<span class=\"SD\" id=\"ID_[\d]{7}\">)([\d]{7})([E|W]{1})", str(aerodromeAd0202))
                    aerodromeElev = re.search(r"(VAL_ELEV\;)([\d]{1,4})", str(aerodromeAd0202))

                    latPM = Geo.plusMinus(aerodromeLat.group(4))
                    lonPM = Geo.plusMinus(aerodromeLon.group(4))
                    fullLocation = latPM + aerodromeLat.group(3) + ".00" + lonPM + aerodromeLon.group(3) + ".00" # AD-2.2 gives aerodrome location as DDMMSS / DDDMMSS

                    dfAd01.at[index, 'verified'] = 1
                    dfAd01.at[index, 'magnetic_variation'] = str(floatMagVar)
                    dfAd01.at[index, 'location'] = str(fullLocation)
                    dfAd01.at[index, 'elevation'] = str(aerodromeElev[2])

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

                        dfOut = {'icao_designator': str(aeroIcao),'runway': str(rwy),'location': str(loc),'elevation': str(elev),'bearing': str(brg.rstrip('°')),'length': str(rwyLen)}
                        dfRwy = dfRwy.append(dfOut, ignore_index=True)

                    # Find air traffic services
                    aerodromeServices = self.search("(APPROACH|GROUND|DELIVERY|TOWER|DIRECTOR|INFORMATION)", "TCALLSIGN_DETAIL", str(aerodromeAd0218))
                    serviceFrequency = self.search("([\d]{3}\.[\d]{3})", "TFREQUENCY", str(aerodromeAd0218))

                    for srv, frq in zip(aerodromeServices, serviceFrequency):
                        #callSignId = "SELECT id FROM standard_callsigns WHERE description = '"+ str(srv) +"' LIMIT 1"
                        #callSignType = mysqlExec(callSignId, "one")
                        #csModify = re.search(r"([\d]{1,8})", str(callSignType))

                        dfOut = {'icao_designator': str(aeroIcao),'callsign_type': str(srv),'frequency': str(frq)}
                        dfSrv = dfSrv.append(dfOut, ignore_index=True)
                else:
                    print(Fore.RED + "Aerodrome " + aeroIcao + " does not exist" + Style.RESET_ALL)
                bar()
        return [dfAd01, dfRwy, dfSrv]

    def parseEnr016Data(self, dfAd01):
        print("Parsing "+ self.country + "-AD-1.6 data to obtan SSR code allocation plan")
        dfColumns = ['start','end','depart','arrive', 'string']
        df = pd.DataFrame(columns=dfColumns)

        webpage = self.getTableSoup(self.country + "-ENR-1.6-en-GB.html")
        getDiv = webpage.find("div", id = "ENR-1.6.2.6")
        getTr = getDiv.find_all('tr')
        barLength = len(getTr)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in getTr:
                getP = row.find_all('p')
                if len(getP) > 1:
                    text = re.search(r"([\d]{4})...([\d]{4})", getP[0].text) # this will just return ranges and ignore all discreet codes in the table
                    if text:
                        start = text.group(1)
                        end = text.group(2)

                        # create an array of words to search through to try and match code range to destination airport
                        locArray = getP[1].text.split()
                        for loc in locArray:
                            strip = re.search(r"([A-Za-z]{3,10})", loc)
                            if strip:
                                dep = "EG\w{2}"
                                # search the dataframe containing icao_codes
                                name = dfAd01[dfAd01['name'].str.contains(strip.group(1), case=False, na=False)]
                                if len(name.index) == 1:
                                    dfOut = {'start': start,'end': end,'depart': dep,'arrive': name.iloc[0]['icao_designator'],'string': strip.group(1)}
                                    df = df.append(dfOut, ignore_index=True)
                                elif strip.group(1) == "RAF" or strip.group(1) == "Military" or strip.group(1) == "RNAS" or strip.group(1) == "NATO":
                                    dfOut = {'start': start,'end': end,'depart': dep,'arrive': 'Military','string': strip.group(1)}
                                    df = df.append(dfOut, ignore_index=True)
                                elif strip.group(1) == "Transit":
                                    dfOut = {'start': start,'end': end,'depart': dep,'arrive': locArray[2],'string': strip.group(1)}
                                    df = df.append(dfOut, ignore_index=True)
                bar()
        return(df)

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

        dfColumns = ['name', 'callsign', 'frequency', 'boundary', 'upper_fl', 'lower_fl']
        dfFir = pd.DataFrame(columns=dfColumns)
        dfUir = pd.DataFrame(columns=dfColumns)

        dfColumns = ['fir_id', 'name', 'boundary']
        dfCta = pd.DataFrame(columns=dfColumns)
        dfTma = pd.DataFrame(columns=dfColumns)

        print("Parsing "+ self.country +"-ENR-2.1 Data (FIR, UIR, TMA AND CTA)...")
        getData = self.getTableSoup(self.country + "-ENR-2.1-en-GB.html")
        searchData = getData.find_all("td")
        barLength = len(searchData)
        with alive_bar(barLength) as bar: # Define the progress bar
            for row in searchData:
                # find all FIR/UIR spaces
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
                        dfOut = {'name': str(firTitle[0]),'callsign': 'NONE','frequency': '000.000', 'boundary': str(boundary), 'upper_fl': str(firUpper[0]), 'lower_fl': str(firLower[0])}
                        dfFir = dfFir.append(dfOut, ignore_index=True)

                        # lazy bit of coding for EG airspace UIR (which has the same extent as FIR)
                        dfOut = {'name': str(firTitle[0]).split()[0] + ' UIR','callsign': 'NONE','frequency': '000.000', 'boundary': str(boundary), 'upper_fl': '660', 'lower_fl': '245'}
                        dfUir = dfUir.append(dfOut, ignore_index=True)

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

                            dfOut = {'fir_id': '0', 'name': str(title), 'boundary': str(boundary)}
                            dfCta = dfCta.append(dfOut, ignore_index=True)
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

                            dfOut = {'fir_id': '0', 'name': str(title), 'boundary': str(boundary)}
                            dfTma = dfTma.append(dfOut, ignore_index=True)
                    else:
                        print(str(tmaTitle) + " complex TMA")
                bar()
        return [dfFir, dfUir, dfCta, dfTma]

    def parseEnr03Data(self, section):
        dfColumns = ['name', 'route']
        dfEnr03 = pd.DataFrame(columns=dfColumns)
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
                    dfOut = {'name': str(getAirwayName[0]), 'route': str(printRoute).rstrip('/')}
                    dfEnr03 = dfEnr03.append(dfOut, ignore_index=True)
                bar()
        return dfEnr03

    def parseEnr04Data(self, sub):
        dfColumns = ['name', 'type', 'coords']
        df = pd.DataFrame(columns=dfColumns)
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
                    dfOut = {'name': str(name[2]), 'type': str(name[1]), 'coords': str(fullLocation)}
                elif sub == "4":
                    # Add fix to the aerodromeDB
                    dfOut = {'name': str(name[1]), 'type': 'FIX', 'coords': str(fullLocation)}

                df = df.append(dfOut, ignore_index=True)
                bar()
        return df

    def run(self):
        Ad01 = self.parseAd01Data() # returns single dataframe
        Ad02 = self.parseAd02Data(Ad01) # returns dfAd01, dfRwy, dfSrv
        Enr016 = self.parseEnr016Data(Ad01) # returns single dataframe
        Enr02 = self.parseEnr02Data() # returns dfFir, dfUir, dfCta, dfTma
        Enr031 = self.parseEnr03Data('1') # returns single dataframe
        Enr033 = self.parseEnr03Data('3') # returns single dataframe
        Enr035 = self.parseEnr03Data('5') # returns single dataframe
        Enr041 = self.parseEnr04Data('1') # returns single dataframe
        Enr044 = self.parseEnr04Data('4') # returns single dataframe

        Ad01.to_csv('Dataframes/Ad01.csv')
        Ad02[1].to_csv('Dataframes/Ad02-Runways.csv')
        Ad02[1].to_csv('Dataframes/Ad02-Services.csv')
        Enr016.to_csv('Dataframes/Enr016.csv')
        Enr02[0].to_csv('DataFrames/Enr02-FIR.csv')
        Enr02[1].to_csv('DataFrames/Enr02-UIR.csv')
        Enr02[2].to_csv('DataFrames/Enr02-CTA.csv')
        Enr02[3].to_csv('DataFrames/Enr02-TMA.csv')
        Enr031.to_csv('DataFrames/Enr031.csv')
        Enr033.to_csv('DataFrames/Enr033.csv')
        Enr035.to_csv('DataFrames/Enr035.csv')
        Enr041.to_csv('DataFrames/Enr041.csv')
        Enr044.to_csv('DataFrames/Enr044.csv')

        return [Ad01, Ad02, Enr016, Enr02, Enr031, Enr033, Enr035, Enr041, Enr044]

    @staticmethod
    def search(find, name, string):
        searchString = find + "(?=<\/span>.*>" + name + ")"
        result = re.findall(rf"{str(searchString)}", str(string))
        return result

class Builder:
    '''Class to build xml files from the dataframes for vatSys'''

    def __init__(self, fileImport=0):
        self.mapCentre = "+53.7-1.5"
        # if there are dataframe files present then use those, else run the webscraper
        if fileImport == 1:
            scrape = []
            scrape.append(pd.read_csv('Dataframes/Ad01.csv', index_col=0))
            scrape.append(pd.read_csv('Dataframes/Ad02-Runways.csv', index_col=0))
            scrape.append(pd.read_csv('Dataframes/Ad02-Services.csv', index_col=0))
            scrape.append(pd.read_csv('Dataframes/Enr016.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr02-FIR.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr02-UIR.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr02-CTA.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr02-TMA.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr031.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr033.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr035.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr041.csv', index_col=0))
            scrape.append(pd.read_csv('DataFrames/Enr044.csv', index_col=0))
            self.scrape = scrape
        else:
            initWebscrape = Webscrape()
            self.scrape = initWebscrape.run()

    def run(self):
        airspace = self.buildAirspaceXml()
        allAirports = self.buildMapsAllAirportsXml()
        allNavaids = self.buildMapsAllNavaidsXml()
        allCta = self.buildOtherTopLevelMaps('ALL_CTA', '2')
        allTma = self.buildOtherTopLevelMaps('ALL_TMA', '2')

        dfAd01 = self.scrape[0]
        dfVerified = dfAd01.loc[dfAd01['verified'] == 1] # select all verified aerodromes (verified as in a page was found in the eAIP corresponding to the icao_designator)
        barLength = len(dfVerified.index)

        with alive_bar(barLength) as bar: # Define the progress bar
            for index, row in dfVerified.iterrows():
                print(Fore.BLUE + "Constructing XML for " + row['icao_designator'] + " ("+ row['name'] +")" + Style.RESET_ALL)
                # set airport name (icao) under Airspace/SystemRunways
                xmlAerodrome = xtree.SubElement(airspace[0], 'Airport')
                xmlAerodrome.set('Name',row['icao_designator'])
                # set airport name (icao) under Airspace/Airports
                xmlAirport = xtree.SubElement(airspace[3], 'Airport')
                xmlAirport.set('ICAO', row['icao_designator'])
                xmlAirport.set('Position', row['location'])
                xmlAirport.set('Elevation', row['elevation'])
                # Set points in Maps\ALL_AIRPORTS.xml
                self.elementPoint(allAirports[0], row['icao_designator']) # set label
                self.elementPoint(allAirports[1], row['icao_designator']) # set symbol

                dfAd02Runways = self.scrape[1]
                dfAd02RunwaysFilter = dfAd02Runways.loc[dfAd02Runways['icao_designator'] == row['icao_designator']] # select all runways that belong to this aerodrome

                for indexRwy, rwy in dfAd02RunwaysFilter.iterrows():
                    xmlRunway = xtree.SubElement(xmlAerodrome, 'Runway')
                    xmlRunway.set('Name', rwy['runway'])
                    xmlRunway.set('DataRunway', rwy['runway'])

                    # create XML maps for each runway
                    #figure out the other end of the runway first
                    oppEndSplit = re.match(r'([\d]{2})([L|R|C])?', rwy['runway'])
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
                bar()

    def buildAirspaceXml(self):
        xmlAirspace = self.root('Airspace') # create XML document Airspace.xml

        # Define subtag SystemRunways, SidStar, Intersections, Airports and Airways - https://virtualairtrafficsystem.com/docs/dpk/#systemrunways
        xmlSystemRunways = xtree.SubElement(xmlAirspace, 'SystemRunways')
        xmlSidStar = xtree.SubElement(xmlAirspace, 'SIDSTARs')
        xmlIntersections = xtree.SubElement(xmlAirspace, 'Intersections')
        xmlAirports = xtree.SubElement(xmlAirspace, 'Airports')
        xmlAirways = xtree.SubElement(xmlAirspace, 'Airways')

        return [xmlSystemRunways, xmlSidStar, xmlIntersections, xmlAirports, xmlAirways]

    def buildMapsAllAirportsXml(self):
        # create XML document Maps\ALL_AIRPORTS
        xmlAllAirports = self.root('Maps')
        xmlAllAirportsMap = self.constructMapHeader(xmlAllAirports, 'System2', 'ALL_AIRPORTS', '2', self.mapCentre)

        xmlAllAirportsLabel = xtree.SubElement(xmlAllAirportsMap, 'Label')
        xmlAllAirportsLabel.set('HasLeader', 'true') # has a line connecting the point and label
        xmlAllAirportsLabel.set('LabelOrientation', 'NW') # where the label will be positioned in relation to the point
        xmlAllAirportsSymbol = xtree.SubElement(xmlAllAirportsMap, 'Symbol')
        xmlAllAirportsSymbol.set('Type', 'Reticle') # https://virtualairtrafficsystem.com/docs/dpk/#symbol-element

        return [xmlAllAirportsLabel, xmlAllAirportsSymbol]

    def buildMapsAllNavaidsXml(self):
        # create XML document Maps\ALL_NAVAIDS
        xmlAllNavaids = self.root('Maps')
        xmlAllNavaidsMap = self.constructMapHeader(xmlAllNavaids, 'System', 'ALL_NAVAIDS_NAMES', '0', self.mapCentre)
        xmlAllNavaidsMapSym = self.constructMapHeader(xmlAllNavaidsMap, 'System', 'ALL_NAVAIDS', '0', self.mapCentre)

        xmlAllNavaidsLabel = xtree.SubElement(xmlAllNavaidsMap, 'Label')
        xmlAllNavaidsLabel.set('HasLeader', 'true') # has a line connecting the point and label

        xmlAllNavaidsSymbol = xtree.SubElement(xmlAllNavaidsMapSym, 'Symbol')
        xmlAllNavaidsSymbol.set('Type', 'Hexagon') # https://virtualairtrafficsystem.com/docs/dpk/#symbol-element
        xmlAllNavaidsSymbolH = xtree.SubElement(xmlAllNavaidsMapSym, 'Symbol')
        xmlAllNavaidsSymbolH.set('Type', 'DotFillCircle') # https://virtualairtrafficsystem.com/docs/dpk/#symbol-element

        return [xmlAllNavaidsLabel, xmlAllNavaidsSymbol, xmlAllNavaidsSymbolH]

    def buildOtherTopLevelMaps(self, mapName, priority):
        xmlRoot = self.root('Maps')
        xmlMap = self.constructMapHeader(xmlRoot, 'System', mapName, priority, self.mapCentre)

        return xmlMap

    @staticmethod
    def root(name):
        # Define the XML root tag
        xml = xtree.Element(name)
        xml.set('xmlns:xsd', 'http://www.w3.org/2001/XMLSchema')
        xml.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')

        # Set a tag for XML generation time
        xml.set('generated', ctime(time()))

        return xml

    @staticmethod
    def constructMapHeader(rootName, mapType, name, priority, center): # ref https://virtualairtrafficsystem.com/docs/dpk/#map-element
        # creates the neccessary header for XML documents in the \Maps folder
        mapHeader = xtree.SubElement(rootName, 'Map')

        mapHeader.set('Type', mapType) # The type primarily will affect the colour vatSys uses to paint the map. Colours are defined in Colours.xml.
        mapHeader.set('Name', name) # The title of the Map (as displayed to the user).
        mapHeader.set('Priority', priority) # An integer specifying the z-axis layering of the map, 0 being drawn on top of everything else.
        if center:
            mapHeader.set('Center', center) # An approximate center point of the map, used to deconflict in the event of multiple Waypoints with the same name.

        return mapHeader

    @staticmethod
    def elementPoint(sub, text):
        point = xtree.SubElement(sub, 'Point')
        point.text = text
        return point

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
new = Builder(1)
new.run()
