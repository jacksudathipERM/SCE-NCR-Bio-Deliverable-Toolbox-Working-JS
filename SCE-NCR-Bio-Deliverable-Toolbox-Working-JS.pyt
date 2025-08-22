import arcpy
import datetime

# ——————————————————————————————————————————————————————————————————————————————————
class Toolbox(object):
    def __init__(self):
        self.label = "ESD Construction Support"
        self.alias = "ESDConstructionSupport"
        # the only tool in this toolbox
        self.tools = [VMExtraction]

# ——————————————————————————————————————————————————————————————————————————————————
class VMExtraction(object):
    def __init__(self):
        self.label = "VM ESD Con Support Monthly Deliverable"
        self.description = (
            "Selects VM survey/monitoring records in a date range, "
            "cleans blanks, spatially joins to SCE districts, and calculates fields."
        )
        self.canRunInBackground = True

    def getParameterInfo(self):
        """Define parameter definitions for the tool dialog."""
        params = []

        # Input VM feature layer (get from agol)
        inVM = arcpy.Parameter(
            displayName="Input VM Survey/Monitoring Layer",
            name="in_vm_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        params.append(inVM)

        # End date
        endDate = arcpy.Parameter(
            displayName="End Date (EndDate ≤)",
            name="end_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input"
        )
        params.append(endDate)

        return params

    def updateParameters(self, parameters):
        # no inter‐param dependencies in this tool
        return

    def updateMessages(self, parameters):
        # nothing custom to validate
        return

    def execute(self, parameters, messages):
        # getting input from user
        vm_survey_and_monitoring = parameters[0].valueAsText
        endDate = parameters[1].valueAsText
        arcpy.AddMessage(f"Troubleshooting enddate: {endDate}")

        temp_data = arcpy.env.scratchGDB
        endDate = endDate.replace("/", "")

        print(f"end date after replace: {endDate}")

        endDate_str = ""
        
        '''
        Formatting date input from month/day/year to year-month-day to fit SQL formatting
        '''
        if int(str(endDate)[0]) < 10 and int(str(endDate)[1]) < 10:
            endDate_str = endDate[2:] + "-" + "0" + endDate[0] + "-" + "0" + endDate[1]
        elif int(str(endDate)[0]) < 10: 
            endDate_str = endDate[2:] + "-" + "0" + endDate[0] + "-" + endDate[1:3]
        elif int(str(endDate)[2]) < 10: 
            endDate_str = endDate[2:] + "-" + endDate[0] + "-" + "0" + endDate[2]

        arcpy.AddMessage(f"Troubleshooting enddate rearranging: {endDate_str}")

        try:
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")

            output_gdb = r"M:\US\Projects\S-U\SoCal_Edison\SCE ESD Construction Support\Data\TEST_Py_Toolbox_Deliverable_Output.gdb"
            districts = r"M:\US\Projects\S-U\SoCal_Edison\SCE ESD Construction Support\Data\SCE_Data.gdb\SCE_DIstricts"
            schema = r"M:\US\Projects\S-U\SoCal_Edison\SCE ESD Construction Support\Tools\ESD monthly deliverable pyt\ESD_ConSup_VM.gdb\ESD_ConSup_VM_Schema"

            arcpy.AddMessage(f"Location of output feature class: {schema}")

            arcpy.AddMessage("Clearing schema")
            if arcpy.Exists(schema):
                arcpy.management.SelectLayerByAttribute(
                    in_layer_or_view=schema,
                    selection_type="SWITCH_SELECTION"
                )
                arcpy.management.DeleteFeatures(schema)


            arcpy.env.overwriteOutput = True

            arcpy.AddMessage(f"debugging checking end date var: {endDate_str}")

            # data select using sql query
            data_select_sql = (
                "("
                "EndDate >= timestamp '1984-05-02 00:00:00' AND "
                f"EndDate < timestamp '{endDate_str} 00:00:00' AND "
                "BioFieldType <> 'TBD' AND "
                "ConsultantProjectIdentifier NOT LIKE '%Z%' AND "
                "ConsultantProjectIdentifier NOT LIKE '%test%' AND "
                "ConsultantProjectIdentifier NOT LIKE '%Test%' AND "
                "ERM_Delivered_Date IS NULL AND "
                "EndDate IS NOT NULL AND "
                "ERM_Form_Type IS NOT NULL"
                ") AND ("
                "(BioFieldType = 'Pre-Activity Survey' AND ERM_Begin_Survey = 'Yes') OR "
                "(BioFieldType = 'Monitoring' AND ERM_Form_Type IN ('Bio and Waters Monitoring', 'Bio Monitoring', 'Waters Monitoring')) OR "
                "(WatersFieldType = 'Monitoring' AND ERM_Form_Type IN ('Bio and Waters Monitoring', 'Waters Monitoring'))"
                ")"
            )

            arcpy.AddMessage(f"debugging data select sql lines: {data_select_sql}")

            data_select = rf"{temp_data}\data_select_{timestamp}"
            arcpy.analysis.Select(vm_survey_and_monitoring, data_select, data_select_sql)
            arcpy.AddMessage("data select completed")

            # convert blank values to nulls
            fieldNames = [f.name for f in arcpy.ListFields(data_select)]
            fieldCount = len(fieldNames)
            with arcpy.da.UpdateCursor(data_select, fieldNames) as cursor:
                for row in cursor:
                    curr_row = row
                    for field in range(fieldCount):
                        if curr_row[field] == "":
                            curr_row[field] = None

                    cursor.updateRow(curr_row)
            del cursor
            arcpy.AddMessage("convert blank values to nulls complete")

            # spatial join: joining data select with districts 
            joined_fc = rf"{temp_data}\data_w_districts_{timestamp}"
            arcpy.analysis.SpatialJoin(data_select, districts, joined_fc,join_operation="JOIN_ONE_TO_ONE", match_option="INTERSECT")
            arcpy.AddMessage("spatial join data select and districts completed")

            # Using update cursor to look for null values and replace to fit sce needs
            with arcpy.da.UpdateCursor(joined_fc, ['ConsultantProjectIdentifier', 'NAME', 'Number_', 'District']) as cursor:
                for row in cursor: 
                    if row[1] == None and row[2] == None:
                        row[1] = "Outside District"
                        row[2] = "99"
                        row[3] = 99
                        cursor.updateRow(row)
            arcpy.AddMessage("replcing nulled district name and number completed")


            # feld calculating bio and water survey and monitoring fields 
            bio_water_names = """def get_name(erm_col, first_name, form_type):
                if form_type == "Bio Monitoring" or form_type == "Bio and Waters Monitoring":
                    return f"{erm_col}, {first_name}"
                elif form_type == "Waters Monitoring" or form_type == "Bio and Waters Monitoring":
                    return f"{erm_col}, {first_name}"
                elif form_type == "Pre-Activity Survey":
                    return f"{erm_col}, {first_name}"
            """

            arcpy.management.CalculateFields(
                in_table=joined_fc,
                expression_type="PYTHON3",
                fields=[
                    ["BS_SurveyorName", "get_name(!ERM_SurveyorName!, !ERM_FirstName!, !ERM_Form_Type!)"],
                    ["WM_MonName", "get_name(!ERM_SurveyorName!, !ERM_FirstName!, !ERM_Form_Type!)"],
                    ["BM_MonitorName", "get_name(!ERM_SurveyorName!, !ERM_FirstName!, !ERM_Form_Type!)"]
                ],
                code_block=bio_water_names
            )
            arcpy.AddMessage("field calculating bio surveyor first and last name completed")

            # Field calculate
            arcpy.management.CalculateFields(
                in_table=joined_fc,
                expression_type="PYTHON3",
                fields=[
                    ["StructureFacility", "'Structure'"],
                    ["PrimeConsultant", "'ERM West'"], 
                    ["SCE_SME_Name", "'Victoria Parsons'"],
                    ["TimeIn", "!StartDate!"]
                ]
            )
            arcpy.AddMessage("field calculating static information completed")

            get_project_id="""def get_project_id(location_id, cons_proj_id):
            return location_id[-80:] + "-ConSup-ERM-" + cons_proj_id[-80:]
            """

            arcpy.management.CalculateField(
                in_table=joined_fc,
                expression_type="PYTHON3",
                field="SCEProjectIdentifier",
                expression="get_project_id(!LocationID!, !ConsultantProjectIdentifier!)",
                code_block=get_project_id
            )

            # Calculating geometry for UTM mE and UTM mN
            arcpy.management.CalculateGeometryAttributes(
                in_features=joined_fc,
                geometry_property=[
                    ["UTM_mE", "POINT_X"],
                    ["UTM_mN", "POINT_Y"]
                ],
                coordinate_system=arcpy.SpatialReference(26911),
                coordinate_format="SAME_AS_INPUT"
            )
            arcpy.AddMessage("calculating UTM completed")

            # Calculating all NA values in Safety Issues to 'True'

            na_to_true = """def na_to_true(input):
                    if input == 'true': 
                        return r"n/a"
                    else: 
                        return input
            """

            arcpy.management.CalculateField(
                in_table=joined_fc,
                expression_type="PYTHON3",
                field="SafetyIssues_Other",
                expression="na_to_true(!SafetyIssues_Other!)",
                code_block=na_to_true
            )
            arcpy.AddMessage("Field calc na values to true completed")


            arcpy.management.Append(
                inputs=joined_fc, 
                target=schema,
                schema_type="NO_TEST"  
            )
            arcpy.AddMessage("Data appended to SCE Schema completed")

            test_output = rf"{output_gdb}\test_output_append_{timestamp}"
            arcpy.conversion.ExportFeatures(schema, test_output)
            
            arcpy.AddMessage("Tool ran successfully :)")

        except Exception as e:
            arcpy.AddError(f"Error occurred: {e}")
            raise    
# ——————————————————————————————————————————————————————————————————————————————————
