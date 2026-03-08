coulmn_renames = {
    "Starting Position": "Starting Position",
    "Driver Station": "Driver Station",
    "Collecting=0 Feeding=1 Scoring=2 Did Nothing=3": "Auto Actions",
    "Percent Accuarcy in Hub (Increments of 10%, No shooting=N/A)": "Auto Shooting Accuracy %",	
    "Climb L1  N/A=0 N=1 Y=2": "Auto Climb",
    "Active Shift A Collecting=0 Feeding=1 Scoring=2 Defense=3": "Active Shift 1 Actions",
    "Active Shift B Collecting=0 Feeding=1 Scoring=2 Defense=3": "Active Shift 2 Actions",
    "Percent Accuarcy in Hub (Increments of 10%, N`ing=N/A)": "Teleop Shooting Accuracy %",
    "Inactive Shift A Defense=0 Feeder=1 Did Nothing=2" : "Inactive Shift 1 Actions",
    "Inactive Shift B Defense=0 Feeder=1 Did Nothing=2" : "Inactive Shift 2 Actions",
    "Climb L1 N/A=0 N=1 Y=2": "Climb L1",
    "Climb L2 N/A=0 N=1 Y=2": "Climb L2",
    "Climb L3 N/A=0 N=1 Y=2": "Climb L3",
    "Field Navigation Trench=0 Bump=1 Did not leave Alliance Zone=2": "Field Navigation",
    "Collection No Intake=0 Collect NZ=1 Collect Chute=2 Collect AZ Ground=3": "Collection Method",
    "Overcame Defense? N/A=0 N=1 Y=2": "Overcame Defense" 
}

should_be_aut0 = True
def extract_key_mappings(coulmn_name: str, text: str):
    if coulmn_name == "Auto Actions":
        if text == "0":
            return "Collecting"
        elif text == "1":
            return "Feeding"
        elif text == "2":
            return "Scoring"
        elif text == "3":
            return "Did Nothing"
    elif coulmn_name in ["Auto Shooting Accuracy %", "Teleop Shooting Accuracy %"]:
        if text == "N/A":
            return None
        else:
            return int(text.strip('%')) // 10 * 10
    elif coulmn_name == "Auto Climb":
        if text == "0":
            return "N/A"
        elif text == "1":
            return "N"
        elif text == "2":
            return "Y"
    elif coulmn_name in ["Active Shift 1 Actions", "Active Shift 2 Actions"]:
        if text == "0":
            return "Collecting"
        elif text == "1":
            return "Feeding"
        elif text == "2":
            return "Scoring"
        elif text == "3":
            return "Defense"
    elif coulmn_name in ["Inactive Shift 1 Actions", "Inactive Shift 2 Actions"]:
        if text == "0":
            return "Defense"
        elif text == "1":
            return "Feeder"
        elif text == "2":
            return "Did Nothing"
    elif coulmn_name == "Overcame Defense":
        if text == "0":
            return "N/A"
        elif text == "1":
            return "N"
        elif text == "2":
            return "Y"
    elif coulmn_name in ["Climb L1", "Climb L2", "Climb L3"]:
        if text == "0":
            return "N/A"
        elif text == "1":
            return "N"
        elif text == "2":
            return "Y"
    elif coulmn_name == "Field Navigation":
        if text == "0":
            return "Trench"
        elif text == "1":
            return "Bump"
        elif text == "2":
            return "Did not leave Alliance Zone"
    elif coulmn_name == "Collection Method":
        if text == "0":
            return "No Intake"
        elif text == "1":
            return "Collect NZ"
        elif text == "2":
            return "Collect Chute"
        elif text == "3":
            return "Collect AZ Ground"    
    else:
        return text
