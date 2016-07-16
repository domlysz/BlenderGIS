

#Scale/normalize function : linear stretch from lowest value to highest value
#########################################
def scale(inVal, inMin, inMax, outMin, outMax):
	return (inVal - inMin) * (outMax - outMin) / (inMax - inMin) + outMin



def linearInterpo(x1, x2, y1, y2, x):
	#Linear interpolation = y1 + slope * tx
	dx = x2 - x1
	dy = y2-y1
	slope = dy/dx
	tx = x - x1 #position from x1 (target x)
	return y1 + slope * tx
