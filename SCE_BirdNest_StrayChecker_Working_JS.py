import os
import datetime
import arcpy
import pytz
import subprocess
import tempfile
"""This Python script identifies associated child bird nest records that lack corresponding 
parent records. It generates an HTML table and automatically sends email notifications"""

def SendEmail(html="default", subject="Default Subject", toVal='jack.sudathip@erm.com', ccVal='jack.sudathip@erm.com'):
    scriptPath = r'\\SCUSPRDGISFS01\Data\US\Projects\S-U\SoCal_Edison\SCE ESD Construction Support\Data\Scripts\Bird Nest Stray Record Checker\send_email_automation_alerts.vbs'

    # Create a temporary file to hold the HTML content
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html', encoding='utf-8') as temp_html_file:
        temp_html_file.write(html)
        temp_html_path = temp_html_file.name

    print(f"Temporary HTML file created at: {temp_html_path}")

    try:
        # Prepare arguments for the VBScript
        args = [
            "cscript.exe",
            "//nologo",
            scriptPath,
            toVal,
            ccVal,
            subject,
            temp_html_path  # Pass the temp file path as the HTML argument
        ]
        #
        # print("Running subprocess with args:")
        # for i, a in enumerate(args):
        #     print(f"  [{i}]: {repr(a)}")

        # Execute the VBScript
        subprocess.run(args, shell=False, check=True)

    except subprocess.CalledProcessError as e:
        print(f"Error running subprocess: {e}")

    finally:
        # Clean up the temporary file
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)
            print(f"Temporary HTML file deleted: {temp_html_path}")


def timeUPD(dbTime):
    utcmoment_naive = dbTime
    utcmoment = utcmoment_naive.replace(tzinfo=pytz.utc)
    localFormat = "%Y-%m-%d %H:%M:%S"
    timezones = ['America/Los_Angeles']
    for tz in timezones:
        localDatetime = utcmoment.astimezone(pytz.timezone(tz))
        return localDatetime.strftime(localFormat)



def build_html(records):
    """Build HTML table for all missing parent records."""
    if not records:
        return "<p>All Observation Records Have Corresponding Parent Records.</p>"

    html = "<p>The following observation records do not have an associated parent bird nest point:</p>"
    html += '<table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse;">'
    html += '<tr><th>Missing Parent Records (Object ID)</th><th>Observation Date</th><th>Creator</th><th>Bio Company</th></tr>'
    for key, (val, creator_1, bio_company) in records.items():
        html += f'<tr><td>{key}</td><td>{timeUPD(val)}</td><td>{creator_1}</td><td>{bio_company}</td></tr>'
    html += '</table>'
    return html


def main():
    starttime = datetime.datetime.now()
    print("\nSTART TIME:", starttime)

    # Feature services and district layer URLs
    birdPt_url = r'https://services1.arcgis.com/Sh1QwLSVKYk2AYjx/arcgis/rest/services/0602981_EnvClearanceScope_VM_BirdandBioPoints_2024/FeatureServer/0'
    birdTbl_url = r'https://services1.arcgis.com/Sh1QwLSVKYk2AYjx/arcgis/rest/services/0602981_EnvClearanceScope_VM_BirdandBioPoints_2024/FeatureServer/2'

    # Define feature classes and layers (assuming they're accessible via ArcGIS)
    birdPt = birdPt_url
    birdTbl = birdTbl_url

    # Build parentRows set from birdPt feature class
    parentRows = set()
    try:
        with arcpy.da.SearchCursor(birdPt, ['GlobalID']) as cursor:
            for row in cursor:
                parentRows.add(row[0])
    except Exception as e:
        print(f"Error accessing parent feature class: {e}")
        return

    # Build childRows dictionary from birdTbl table
    childRows = {}
    try:
        with arcpy.da.SearchCursor(birdTbl, ['OBJECTID', 'RelativeGlobalID']) as cursor:
            for row in cursor:
                object_id = row[0]
                relative_parent_id = row[1]
                childRows[object_id] = relative_parent_id
    except Exception as e:
        print(f"Error accessing child table: {e}")
        return

    missing_parent_records = {}

    # Cursor to check child records against parent records
    try:
        with arcpy.da.SearchCursor(birdTbl, ['OBJECTID', 'OBS_DATE', 'RelativeGlobalID', 'BIO_NM', 'BIO_CO']) as cursor:
            for r in cursor:
                object_id = r[0]
                obs_date = r[1]
                relative_parent_id = r[2]
                bio = r[3]
                bio_company = r[4]

                if relative_parent_id not in parentRows:
                    print(f"Adding {object_id} (Creator: {bio}) to missing parent records")
                    missing_parent_records[object_id] = (obs_date, bio, bio_company)
    except Exception as e:
        print(f"Error accessing child table: {e}")
        return

    print("Dictionary of Missing Parent Records:", missing_parent_records)

    # Email lists for scenarios with and without missing records
    email_config = {
        "emails_found": 'jack.sudathip@erm.com; jose.rodriguez@erm.com',
        # "emails_found": 'james.cabrera@erm.com',
        #"emails_no_missing": 'Sarah.Nava@erm.com; jack.sudathip@erm.com; mankin.law@erm.com'
        "emails_no_missing": 'jack.sudathip@erm.com; jose.rodriguez@erm.com'
    }

    # Determine email recipients and subject based on missing records
    if missing_parent_records:
        to_emails = email_config["emails_found"]
        subject = "Alert: Missing Parent Records Detected"
    else:
        to_emails = email_config["emails_no_missing"]
        subject = "Notification: All Bird Nest Child Records Have Corresponding Parent Records"

    # Build HTML content
    html_content = build_html(missing_parent_records)

    # print(f"Final HTML Content: {repr(html_content)}")
    SendEmail(html=html_content, toVal=to_emails, subject=subject)

    print("Donesville!! Total run time:", datetime.datetime.now() - starttime)


if __name__ == '__main__':
    main()
