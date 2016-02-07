"""
kmeans1D.py
Author : domlysz@gmail.com
Date : february 2016
License : GPL

This file is part of BlenderGIS.
This is a kmeans implementation optimized for 1D data.

Original kmeans code :
https://gist.github.com/iandanforth/5862470

1D optimizations are inspired from this talking :
http://stats.stackexchange.com/questions/40454/determine-different-clusters-of-1d-data-from-database

Optimizations consists to :
-sort the data and initialize clusters with a quantile classification
-compute distance in 1D instead of euclidean
-optimize only the borders of the clusters instead of test each cluster values

Clustering results are similar to Jenks natural break and ckmeans algorithms.
There are Python implementations of these alg. based on javascript code from simple-statistics library :
* Jenks : https://gist.github.com/llimllib/4974446 (https://gist.github.com/tmcw/4977508)
* Ckmeans : https://github.com/llimllib/ckmeans (https://github.com/simple-statistics/simple-statistics/blob/master/src/ckmeans.js)

But both are terribly slow, even standard kmeans alg. gives better running times.
In contrast, this script works in a reasonable time. 
"""

import math


def kmeans1d(data, k, cutoff=0.1):
	'''
	Compute natural breaks of a one dimensionnal list through an optimized kmeans algorithm
	Inputs:
	* data = input list, must be sorted beforehand
	* k = number of expected classes
	* cutoff = stop algorithm when centroids shift are under this value
	Output:
	* A list of k clusters. A cluster is represented by a tuple containing first and last index of the cluster's values.
	Use these index on the input data list to retreive the effectives values containing in a cluster.
	'''

	def getClusterValues(cluster):
		i, j = cluster
		return data[i:j]
		
	def getClusterCentroid(cluster):
		values = getClusterValues(cluster)
		return sum(values) / len(values)
		
	# Step 1: Create k clusters with quantile classification
	n = len(data)
	q = int(math.ceil(n/k))
	clusters = [ [i, i+q+1] for i in range(0,n,q)] #store only first and last index
	clusters[-1][1] = n-1 #adjust the last index of the last cluster

	#Centroid = mean = virtual center point for a group of 1-dimensional values
	centroids = [getClusterCentroid(c) for c in clusters]

	# Loop through the dataset until the clusters stabilize
	loopCounter = 0
	while True:		
		loopCounter += 1
		
		# Step 2 : for each cluster...
		for i in range(k-1): #do not process last cluster
			c1 = clusters[i] #current cluster
			c2 = clusters[i+1] #next cluster

			# Test the distance between the right border of the current cluster and the neightbors centroids
			# Move the values if it's closer to the next cluster's centroid. 
			# Then, test the new right border or stop if no more move is needed.
			while True:
				if c1[0] + 1 == c1[1]:
					# only one value remaining in the current cluster
					# stop executing any more move to avoid having an empty cluster
					break
				breakValue = data[c1[1]]
				dst1 = abs(breakValue - centroids[i])
				dst2 = abs(breakValue - centroids[i+1])
				if dst1 > dst2:
					# Adjust border : move last value of the current cluster to the next cluster
					c1[1] -= 1 #decrease right border index of current cluster
					c2[0] -= 1 #decrease left border index of the next cluster
				else:
					break		
			
			# Test the distance between the left border of the next cluster and the neightbors centroids
			# Move the values if it's closer to the current cluster's centroid. 
			# Then, test the new left border or stop if no more move is needed.					
			while True:
				if c2[0] + 1 == c2[1]:
					# only one value remaining in the next cluster
					# stop executing any more move to avoid having an empty cluster
					break
				breakValue = data[c2[0]]
				dst1 = abs(breakValue - centroids[i])
				dst2 = abs(breakValue - centroids[i+1])
				if dst2 > dst1:
					# Adjust border : move first value of the next cluster to the current cluster
					c2[0] += 1 #increase left border index of the next cluster
					c1[1] += 1 #increase right border index of current cluster
				else:
					break		
					
		# Step 3: update centroids and stop main loop if they have stopped moving much
		biggest_shift = 0
		for i in range(k):
			# Compute cluster centroid according to new affected values
			c = clusters[i]
			newCentroid = getClusterCentroid(c)
			# calculate how far the centroid moved in this iteration
			shift = abs(newCentroid - centroids[i])
			# Keep track of the largest move from all cluster centroid updates
			biggest_shift = max(biggest_shift, shift)
			# Update centroid value
			centroids[i] = newCentroid
		# If the centroids have stopped moving much, say we're done!
		if biggest_shift < cutoff:
			print("Converged after %s iterations" % loopCounter)
			break

	return clusters


#-----------------
#Helpers to get values from clusters's indices list returning by kmeans1d function

def getClustersValues(data, clusters):
	return [data[i:j+1] for i, j in clusters]
	
def getBreaks(data, clusters, includeBounds=False):
	if includeBounds:
		return [data[0]] + [data[j] for i, j in clusters]
	else:
		return [data[j] for i, j in clusters[:-1]]	
	
	


if __name__ == '__main__':
	import random, time
	
	#make data with a gap between 1000 and 2000
	data = [random.uniform(0, 1000) for i in range(10000)]
	data.extend([random.uniform(2000, 4000) for i in range(10000)])
	data.sort()
	
	k = 4
	cutoff = 0.1
	
	print('---------------')
	print('%i values, %i classes' %(len(data),k))
	t1 = time.clock()
	clusters = kmeans1d(data, k, cutoff)
	t2 = time.clock()
	print('Completed in %f seconds' %(t2-t1))

	print('Breaks :')
	print(getBreaks(data, clusters))
	
	print('Clusters details (nb values, min, max) :')
	for clusterValues in getClustersValues(data, clusters):
		print( len(clusterValues), clusterValues[0], clusterValues[-1] )

