"""
Hop is a script to raise the extruder when it is not extruding.

The default 'Activate Hop' checkbox is on.  When it is on, the functions described below will work, when it is off, the functions
will not be called.

The important value for the hop preferences is "Hop Over Extrusion Height (ratio)" which is the ratio of the hop height over the
extrusion height, the default is 1.0.  The 'Minimum Hop Angle (degrees)' is the minimum angle that the path of the extruder
will be raised.  An angle of ninety means that the extruder will go straight up as soon as it is not extruding and a low angle
means the extruder path will gradually rise to the hop height, the default is 20 degrees.

To run hop, in a shell which hop is in type:
> python hop.py

The following examples hop the files Hollow Square.gcode & Hollow Square.gts.  The examples are run in a terminal in the
folder which contains Hollow Square.gcode, Hollow Square.gts and hop.py.  The hop function will hop if the 'Activate Hop'
checkbox is on.  The functions writeOutput and getHopChainGcode check to see if the text has been hopped, if not they
call the getStretchChainGcode in stretch.py to stretch the text; once they have the stretched text, then they hop.


> python hop.py
This brings up the dialog, after clicking 'Hop', the following is printed:
File Hollow Square.gts is being chain hopped.
The hopped file is saved as Hollow Square_hop.gcode


> python
Python 2.5.1 (r251:54863, Sep 22 2007, 01:43:31)
[GCC 4.2.1 (SUSE Linux)] on linux2
Type "help", "copyright", "credits" or "license" for more information.
>>> import hop
>>> hop.main()
This brings up the hop dialog.


>>> hop.writeOutput()
Hollow Square.gts
File Hollow Square.gts is being chain hopped.
The hopped file is saved as Hollow Square_hop.gcode


>>> hop.getHopGcode("
( GCode generated by May 8, 2008 slice.py )
( Extruder Initialization )
..
many lines of gcode
..
")


>>> hop.getHopChainGcode("
( GCode generated by May 8, 2008 slice.py )
( Extruder Initialization )
..
many lines of gcode
..
")

"""

from __future__ import absolute_import
#Init has to be imported first because it has code to workaround the python bug where relative imports don't work if the module is imported as a main module.
import __init__

from skeinforge_tools.skeinforge_utilities import euclidean
from skeinforge_tools.skeinforge_utilities import gcodec
from skeinforge_tools.skeinforge_utilities import preferences
from skeinforge_tools import analyze
from skeinforge_tools import polyfile
from skeinforge_tools import stretch
import cStringIO
import math
import time


__author__ = "Enrique Perez (perez_enrique@yahoo.com)"
__date__ = "$Date: 2008/21/04 $"
__license__ = "GPL 3.0"


def getHopChainGcode( gcodeText, hopPreferences = None ):
	"Hop a gcode linear move text.  Chain hop the gcode if it is not already hopped."
	if not gcodec.isProcedureDone( gcodeText, 'stretch' ):
		gcodeText = stretch.getStretchChainGcode( gcodeText )
	return getHopGcode( gcodeText, hopPreferences )

def getHopGcode( gcodeText, hopPreferences = None ):
	"Hop a gcode linear move text."
	if gcodeText == '':
		return ''
	if gcodec.isProcedureDone( gcodeText, 'hop' ):
		return gcodeText
	if hopPreferences == None:
		hopPreferences = HopPreferences()
		preferences.readPreferences( hopPreferences )
	if not hopPreferences.activateHop.value:
		return gcodeText
	skein = HopSkein()
	skein.parseGcode( gcodeText, hopPreferences )
	return skein.output.getvalue()

def writeOutput( filename = '' ):
	"Hop a gcode linear move file.  Chain hop the gcode if it is not already hopped. If no filename is specified, hop the first unmodified gcode file in this folder."
	if filename == '':
		unmodified = gcodec.getGNUGcode()
		if len( unmodified ) == 0:
			print( "There are no unmodified gcode files in this folder." )
			return
		filename = unmodified[ 0 ]
	hopPreferences = HopPreferences()
	preferences.readPreferences( hopPreferences )
	startTime = time.time()
	print( 'File ' + gcodec.getSummarizedFilename( filename ) + ' is being chain hopped.' )
	gcodeText = gcodec.getFileText( filename )
	if gcodeText == '':
		return
	suffixFilename = filename[ : filename.rfind( '.' ) ] + '_hop.gcode'
	hopGcode = getHopChainGcode( gcodeText, hopPreferences )
	gcodec.writeFileText( suffixFilename, hopGcode )
	print( 'The hopped file is saved as ' + gcodec.getSummarizedFilename( suffixFilename ) )
	analyze.writeOutput( suffixFilename, hopGcode )
	print( 'It took ' + str( int( round( time.time() - startTime ) ) ) + ' seconds to hop the file.' )


class HopSkein:
	"A class to hop a skein of extrusions."
	def __init__( self ):
		self.bridgeExtrusionWidthOverSolid = 1.0
		self.decimalPlacesCarried = 3
		self.extruderActive = False
		self.feedrateString = ''
		self.hopHeight = 0.4
		self.layerHopDistance = self.hopHeight
		self.layerHopHeight = self.hopHeight
		self.justDeactivated = False
		self.lineIndex = 0
		self.lines = None
		self.oldLocation = None
		self.output = cStringIO.StringIO()

	def addLine( self, line ):
		"Add a line of text and a newline to the output."
		self.output.write( line + "\n" )

	def getHopLine( self, line ):
		"Get hopped gcode line."
		splitLine = line.split( ' ' )
		indexOfF = gcodec.indexOfStartingWithSecond( "F", splitLine )
		if indexOfF > 0:
			self.feedrateString = splitLine[ indexOfF ]
		if self.extruderActive:
			return line
		location = gcodec.getLocationFromSplitLine( self.oldLocation, splitLine )
		if self.isNextTravel():
			return self.getMovementLineWithHop( location )
		if self.justDeactivated:
			distance = location.distance( self.oldLocation )
			alongRatio = min( 0.41666666, self.layerHopDistance / distance )
			oneMinusAlong = 1.0 - alongRatio
			closeLocation = self.oldLocation.times( oneMinusAlong ).plus( location.times( alongRatio ) )
			self.addLine( self.getMovementLineWithHop( closeLocation ) )
			farLocation = self.oldLocation.times( alongRatio ).plus( location.times( oneMinusAlong ) )
			self.addLine( self.getMovementLineWithHop( farLocation ) )
		return line

	def getMovementLineWithHop( self, location ):
		"Get linear movement line for a location."
		#add hop
		movementLine = 'G1 X%s Y%s Z%s' % ( self.getRounded( location.x ), self.getRounded( location.y ), self.getRounded( location.z + self.layerHopHeight ) )
		if self.feedrateString != '':
			movementLine += ' ' + self.feedrateString
		return movementLine

	def getRounded( self, number ):
		"Get number rounded to the number of carried decimal places as a string."
		return euclidean.getRoundedToDecimalPlaces( self.decimalPlacesCarried, number )

	def isNextTravel( self ):
		"Determine if there is another linear travel before the thread ends."
		for afterIndex in range( self.lineIndex + 1, len( self.lines ) ):
			line = self.lines[ afterIndex ]
			splitLine = line.split( ' ' )
			firstWord = "";
			if len( splitLine ) > 0:
				firstWord = splitLine[ 0 ]
			if firstWord == 'G1':
				return True
			if firstWord == 'M101':
				return False
		return False

	def parseGcode( self, gcodeText, hopPreferences ):
		"Parse gcode text and store the hop gcode."
		self.lines = gcodec.getTextLines( gcodeText )
		self.minimumSlope = math.tan( math.radians( hopPreferences.minimumHopAngle.value ) )
		self.parseInitialization( hopPreferences )
		for self.lineIndex in range( self.lineIndex, len( self.lines ) ):
			line = self.lines[ self.lineIndex ]
			self.parseLine( line )

	def parseInitialization( self, hopPreferences ):
		"Parse gcode initialization and store the parameters."
		for self.lineIndex in range( len( self.lines ) ):
			line = self.lines[ self.lineIndex ]
			splitLine = line.split( ' ' )
			firstWord = ''
			if len( splitLine ) > 0:
				firstWord = splitLine[ 0 ]
			if firstWord == '(<extrusionHeight>':
				extrusionHeight = float( splitLine[ 1 ] )
				self.hopHeight = hopPreferences.hopOverExtrusionHeight.value * extrusionHeight
			elif firstWord == '(<bridgeExtrusionWidthOverSolid>':
				self.bridgeExtrusionWidthOverSolid = float( splitLine[ 1 ] )
			elif firstWord == '(<decimalPlacesCarried>':
				self.decimalPlacesCarried = int( splitLine[ 1 ] )
			elif firstWord == '(<extrusionStart>':
				self.addLine( '(<procedureDone> hop )' )
				return
			self.addLine( line )

	def parseLine( self, line ):
		"Parse a gcode line and add it to the bevel gcode."
		splitLine = line.split( ' ' )
		if len( splitLine ) < 1 or len( line ) < 1:
			return
		firstWord = splitLine[ 0 ]
		if firstWord == 'G1':
			line = self.getHopLine( line )
			self.oldLocation = gcodec.getLocationFromSplitLine( self.oldLocation, splitLine )
			self.justDeactivated = False
		if firstWord == 'M101':
			self.extruderActive = True
		if firstWord == 'M103':
			self.extruderActive = False
			self.justDeactivated = True
		elif firstWord == '(<layerStart>':
			self.layerHopHeight = self.hopHeight
			self.layerHopDistance = self.layerHopHeight / self.minimumSlope
		elif firstWord == '(<bridgeLayer>':
			self.layerHopHeight = self.hopHeight * self.bridgeExtrusionWidthOverSolid
			self.layerHopDistance = self.layerHopHeight / self.minimumSlope
		self.addLine( line )


#get hop distance
class HopPreferences:
	"A class to handle the hop preferences."
	def __init__( self ):
		"Set the default preferences, execute title & preferences filename."
		#Set the default preferences.
		self.archive = []
		self.activateHop = preferences.BooleanPreference().getFromValue( 'Activate Hop', True )
		self.archive.append( self.activateHop )
		self.filenameInput = preferences.Filename().getFromFilename( [ ( 'GNU Triangulated Surface text files', '*.gts' ), ( 'Gcode text files', '*.gcode' ) ], 'Open File to be Hoped', '' )
		self.archive.append( self.filenameInput )
		self.hopOverExtrusionHeight = preferences.FloatPreference().getFromValue( 'Hop Over Extrusion Height (ratio):', 1.0 )
		self.archive.append( self.hopOverExtrusionHeight )
		self.minimumHopAngle = preferences.FloatPreference().getFromValue( 'Minimum Hop Angle (degrees):', 20.0 )
		self.archive.append( self.minimumHopAngle )
		#Create the archive, title of the execute button, title of the dialog & preferences filename.
		self.executeTitle = 'Hop'
		self.filenamePreferences = preferences.getPreferencesFilePath( 'hop.csv' )
		self.filenameHelp = 'skeinforge_tools.hop.html'
		self.saveTitle = 'Save Preferences'
		self.title = 'Hop Preferences'

	def execute( self ):
		"Hop button has been clicked."
		filenames = polyfile.getFileOrGNUUnmodifiedGcodeDirectory( self.filenameInput.value, self.filenameInput.wasCancelled )
		for filename in filenames:
			writeOutput( filename )


def main( hashtable = None ):
	"Display the hop dialog."
	preferences.displayDialog( HopPreferences() )

if __name__ == "__main__":
	main()
