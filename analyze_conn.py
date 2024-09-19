import params
import requests
from requests.auth import HTTPDigestAuth
import json
import pprint
import pymongo
from pymongo import MongoClient

print("\nMongoDB Atlas Connection Analysis Tool\n")

# Single octet accless list entries
single_octets = []

# Return the 1st 2 octets of an IP address
def getNetwork(ip):
    ip_octets = ip.split('.')

    # Track access list entries that only define the 1st octet.
    if ip_octets[1] == "0":
        single_octets.append(ip_octets[0])

    # If the IP address is in our list of single octet whitlist entries, then just return this 1st octect
    if ip_octets[0] in single_octets:
        network = ip_octets[0]
    else:
        network = ip_octets[0] + "." + ip_octets[1]

    return network

# A function to print a row of results
def print_row(source, count):
    print(" %-45s %10s" % (source, count))

def printResults(Title, active, accessList, connections):
    pipeline =  [
    {
        '$match': {
            'active': active,
            'whitelist': accessList
        }
    }, {
        '$group': {
            '_id': '$desc', 
            'total_connections': {
                '$sum': 1
            }
        }
    }, {
        '$sort': {
            'total_connections': -1
        }
    }
    ]   
    results = db.connection_analysis.aggregate(pipeline)
    print( "\n            ==== " + Title + " Operations (" + str(connections) + ") ====")
    print_row('Connection Source', 'Connections')
    for conn in results:
        print_row(conn['_id'], conn['total_connections'])

# Establish connection to Atlas
client = MongoClient(params.conn_string)
db = client[params.database]

## Set up PrettyPrinter
pp = pprint.PrettyPrinter(depth=6)

## Get Access List Entries
url = "https://cloud.mongodb.com/api/atlas/v1.0/groups/" + params.project_id +"/whitelist"
resp = requests.get(url, auth=HTTPDigestAuth(params.user, params.password))

if(resp.ok):

    ## Grab the white list entries, remove the subnet mask and create a new dict w/ just the 
    ## first 2 octets a they key. 

    # A new dict for the access list entries
    whitelist_clean = {}

    # Convert the JSON response to a dict
    whitelist = json.loads(resp.content)    
    print ("There are {0} access list entries".format(len(whitelist["results"])))
    
    ## Pretty print the results
    #print(json.dumps(whitelist["results"], indent=4, sort_keys=True))
    
    # Get the IP Address and Description and add to the new whitelist_clean dict
    for key in whitelist["results"]:
        
        if('comment' in key.keys()):
            description = key['comment']
        else:
            description = ""       

        cidr = key['cidrBlock']
        whitelist_ip_mask = cidr.split('/')
        whitelist_ip = whitelist_ip_mask[0]

        ## Ideally the access list entry includes at least 2 octets of the IP address. If not, we'll deal with it.
        network = getNetwork(whitelist_ip)
        entry = {}
        entry['ip'] = whitelist_ip
        entry['desc'] = description
        whitelist_clean[network] = entry

    # pp.pprint(whitelist_clean)

    # Get the current operations running on MongoDB
    # Deprecated - https://pymongo.readthedocs.io/en/stable/migrate-to-pymongo4.html#database-current-op-is-removed
    # opData = db.current_op(True)
    # https://www.mongodb.com/docs/manual/reference/operator/aggregation/currentOp/
    opData = list(client.admin.aggregate([{'$currentOp': {"allUsers": True, "idleConnections": True}}]))

    print ("There are {0} current operations".format(len(opData)))
    print("")
        
    # Drop the existing operations and connection_analysis collection
    db.operations.drop()
    db.connection_analysis.drop()

    for op in opData:
        
        # Store the current operations in MongoDB (this is optional)
        #db.operations.insert_one(op)
        
        # Create a new connection object to store in MongoDB
        conn = {}
        conn['active'] = op['active']

        # We're most intersted in operations that have a client
        if 'client' in op:
            client = op['client']
            client_ip_port = client.split(':')
            client_ip = client_ip_port[0]

            conn['ip'] = client_ip

            network = getNetwork(client_ip)

            if network in whitelist_clean:    # This will skip local IPs like 192. or 127.
                conn['desc'] = whitelist_clean[network]['desc']
                conn['whitelist'] = True
            else:
                conn['desc'] = 'System'
                conn['whitelist'] = False
        
        # Log operations w/out a client (internal w/ no access list entry)
        else:
            conn['desc'] = op['desc']
            conn['whitelist'] = False

        # Add the record to MongoDB
        db.connection_analysis.insert_one(conn)

    ## Analyze the results
    active_conns = db.connection_analysis.count_documents({'active':True})
    dormant_conns = db.connection_analysis.count_documents({'active':False})
    active_wl_conns = db.connection_analysis.count_documents({'active':True, 'whitelist':True})
    dormant_wl_conns = db.connection_analysis.count_documents({'active':False, 'whitelist':True})
    active_sys_conns = db.connection_analysis.count_documents({'active':True, 'whitelist':False})
    dormant_sys_conns = db.connection_analysis.count_documents({'active':False, 'whitelist':False})

    print("Active Operations:" + str(active_conns))
    print("Dormant Operations:" + str(dormant_conns))

    # Active Access List Connections Summary
    printResults("Active Access List", True, True, active_wl_conns)

    # Active System Connections Summary
    printResults("Active System", True, False, active_sys_conns)

    # Dormant Access L:ist Connections Summary
    printResults("Dormant Access List", False, True, dormant_wl_conns)

    # Dormant System Connections Summary
    printResults("Dormant System", False, False, dormant_sys_conns)
        
else:
    resp.raise_for_status()

print("\nAnalysis Complete")
