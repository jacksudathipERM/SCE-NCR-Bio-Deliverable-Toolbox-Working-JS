import arcpy
import datetime

# =============================================================================
# CONFIG: shared paths (edit these once to match your env)
# =============================================================================
WORKING_GDB = r"M:\US\Projects\S-U\SoCal_Edison\SCE ESD Construction Support\Data\WORKING.gdb"
WORKING_SCRATCH = r"M:\US\Projects\S-U\SoCal_Edison\SCE ESD Construction Support\Working\_ArcGIS\2021\SarahN_Working\SarahN_Working.gdb"

# Targets that hold the rolling, month-specific “schema” content (your model #3 clears these)
BIO_SPECIES_POINTS = rf"{WORKING_GDB}\BioSpecies_Points"
BIRD_NESTS_POINTS  = rf"{WORKING_GDB}\Bird_Nests_Points"

# “Export” staging tables produced by models #1/#2 and consumed by #1/#4 appends
BIO_SPECIES_EXPORT   = rf"{WORKING_GDB}\BioSpecies_Export"
BIRD_NESTPOINTS_EXPORT = rf"{WORKING_GDB}\BirdNestPoints_Export"

# Feature service layer paths for BSP export (update to whatever you actually point to in Pro)
BSP_FS_2025 = r"0602981_EnvClearanceScope_VM_BirdandBioPoints_2025\BioSpecies_Points_2025"
BSP_FS_2024 = r"https:\\services1.arcgis.com\Sh1QwLSVKYk2AYjx\arcgis\rest\services\0602981_EnvClearanceScope_VM_BirdandBioPoints_2024\FeatureServer\1"

arcpy.env.overwriteOutput = False


# =============================================================================
# Small helpers
# =============================================================================
def _ts(dt: datetime.datetime) -> str:
    """Return YYYY-MM-DD 00:00:00 for file gdb SQL timestamp literal."""
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime(dt.year, dt.month, dt.day)
    return dt.strftime("%Y-%m-%d 00:00:00")

def _delete_rows(in_table: str):
    if arcpy.Exists(in_table):
        arcpy.AddMessage(f"Deleting rows in: {in_table}")
        arcpy.management.DeleteRows(in_table)
    else:
        arcpy.AddWarning(f"Table not found (skip delete): {in_table}")

def _calc_geometry_utm11(in_fc: str):
    arcpy.management.CalculateGeometryAttributes(
        in_features=in_fc,
        geometry_property=[["UTM_mE", "POINT_X"], ["UTM_mN", "POINT_Y"]],
        coordinate_system="PROJCS[\"NAD_1983_UTM_Zone_11N\",GEOGCS[\"GCS_North_American_1983\",DATUM[\"D_North_American_1983\",SPHEROID[\"GRS_1980\",6378137.0,298.257222101]],PRIMEM[\"Greenwich\",0.0],UNIT[\"Degree\",0.0174532925199433]],PROJECTION[\"Transverse_Mercator\"],PARAMETER[\"False_Easting\",500000.0],PARAMETER[\"False_Northing\",0.0],PARAMETER[\"Central_Meridian\",-117.0],PARAMETER[\"Scale_Factor\",0.9996],PARAMETER[\"Latitude_Of_Origin\",0.0],UNIT[\"Meter\",1.0]]"
    )

def _calc_copy_field(in_table: str, out_field: str, expr: str, expr_type="PYTHON3"):
    arcpy.management.CalculateField(in_table=in_table, field=out_field, expression=expr, expression_type=expr_type)


# =============================================================================
# FIELD MAPPING PAYLOADS (paste your full strings once here)
# =============================================================================
# These are the long, model-generated field mappings used by Append. Paste the exact
# text from your model runs to keep parity.

BSP_APPEND_FIELD_MAPPING = r"""<<<PASTE_BSP_FIELD_MAPPING_FROM_YOUR_MODEL_HERE>>>"""
BNP_APPEND_FIELD_MAPPING = r"""<<<PASTE_BNP_FIELD_MAPPING_FROM_YOUR_MODEL_HERE>>>"""


# =============================================================================
# Toolbox + 4 tools
# =============================================================================
class Toolbox(object):
    def __init__(self):
        self.label = "NCR Bio Deliverable"
        self.alias = "NCRBioDeliverable"
        self.tools = [
            ExportBNPAndCalculate,        # (1)
            ExportBSPFS,                  # (2)
            RemovePreviousMonthRecords,   # (3)
            AppendJoinedBNPsAndBSPsV3     # (4)
        ]


# -----------------------------------------------------------------------------
# (1) Export BNP and Calculate
# Per your shared code, this is effectively the double-Append from export tables
# into the month “schema” datasets (BioSpecies_Points & Bird_Nests_Points),
# with preserveGlobalIds on the first append.
# -----------------------------------------------------------------------------
class ExportBNPAndCalculate(object):
    def __init__(self):
        self.label = "Export BNP and Calculate"
        self.description = "Append BioSpecies_Export and BirdNestPoints_Export into BioSpecies_Points and Bird_Nests_Points (NO_TEST field map)."
        self.canRunInBackground = True

    def getParameterInfo(self):
        # No inputs required; paths are fixed in config. If you want these configurable,
        # add GPFeatureLayer/GPTable params here.
        return []

    def execute(self, parameters, messages):
        with arcpy.EnvManager(scratchWorkspace=WORKING_SCRATCH, workspace=WORKING_SCRATCH):
            # Append BioSpecies Export → BioSpecies_Points
            arcpy.AddMessage("Appending BioSpecies_Export → BioSpecies_Points ...")
            with arcpy.EnvManager(maintainAttachments=False, preserveGlobalIds=True):
                arcpy.management.Append(
                    inputs=[BIO_SPECIES_EXPORT],
                    target=BIO_SPECIES_POINTS,
                    schema_type="NO_TEST",
                    field_mapping=BSP_APPEND_FIELD_MAPPING
                )

            # Append Bird Nest Points Export → Bird_Nests_Points
            arcpy.AddMessage("Appending BirdNestPoints_Export → Bird_Nests_Points ...")
            with arcpy.EnvManager(maintainAttachments=False):
                arcpy.management.Append(
                    inputs=[BIRD_NESTPOINTS_EXPORT],
                    target=BIRD_NESTS_POINTS,
                    schema_type="NO_TEST",
                    field_mapping=BNP_APPEND_FIELD_MAPPING
                )

        arcpy.AddMessage("Export BNP and Calculate — complete.")


# -----------------------------------------------------------------------------
# (2) Export BSP FS (V2)
# Exports from FS to WORKING.gdb\BioSpecies_Export with your where clause,
# then performs the sequence of CalculateField/Geometry steps you listed.
# -----------------------------------------------------------------------------
class ExportBSPFS(object):
    def __init__(self):
        self.label = "Export BSP FS"
        self.description = "Export from BSP FS to WORKING.gdb (BioSpecies_Export) with filters, then run UTM & attribute calculations."
        self.canRunInBackground = True

    def getParameterInfo(self):
        params = []

        # Let the user pick which source layer to export from (default to 2025)
        src = arcpy.Parameter(
            displayName="Source BSP Feature Service Layer",
            name="src_bsp_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input"
        )
        src.value = BSP_FS_2025
        params.append(src)

        # End date driving CreationDate_1 <= timestamp 'END'
        endDate = arcpy.Parameter(
            displayName="End Date (CreationDate_1 ≤)",
            name="end_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input"
        )
        params.append(endDate)

        return params

    def execute(self, parameters, messages):
        src_bsp = parameters[0].valueAsText
        end_dt = parameters[1].value
        if not isinstance(end_dt, datetime.datetime):
            end_dt = datetime.datetime(end_dt.year, end_dt.month, end_dt.day)

        with arcpy.EnvManager(scratchWorkspace=WORKING_SCRATCH, workspace=WORKING_SCRATCH):
            # Build the where clause from your model (parameterized end date)
            end_ts = _ts(end_dt)
            where_clause = (
                "ERM_Delivered_Date IS NULL "
                "And BSP_PT_ID NOT LIKE '%test%' "
                f"And CreationDate_1 <= timestamp '{end_ts}.000'"
            )

            arcpy.AddMessage(f"Exporting BSP FS → {BIO_SPECIES_EXPORT}")
            arcpy.conversion.ExportFeatures(
                in_features=src_bsp,
                out_features=BIO_SPECIES_EXPORT,
                where_clause=where_clause,
                field_mapping=BSP_APPEND_FIELD_MAPPING  # reuse same mapping the append expects
            )

            # SCE OID → EXTRAINFO
            _calc_copy_field(BIO_SPECIES_EXPORT, "EXTRAINFO", "!SCE_OID!")

            # UTM mE/mN (UTM zone 11N)
            _calc_geometry_utm11(BIO_SPECIES_EXPORT)

            # Created/By/Updated/By
            _calc_copy_field(BIO_SPECIES_EXPORT, "CREATEDATE", "!CreationDate_1!")
            _calc_copy_field(BIO_SPECIES_EXPORT, "CREATEBY",  "!BIO_NM!")
            _calc_copy_field(BIO_SPECIES_EXPORT, "UPDATEDATE","!EditDate_1!")
            _calc_copy_field(BIO_SPECIES_EXPORT, "UPDATEBY",  "!BIO_NM!")

            # LEAD_MON (ARCADE literal; Pro accepts PYTHON3 too for a literal string, but staying true to your model)
            _calc_copy_field(BIO_SPECIES_EXPORT, "LEAD_MON", "'Alessandra Phelan-Roberts'", expr_type="ARCADE")

        arcpy.AddMessage("Export BSP FS — complete.")


# -----------------------------------------------------------------------------
# (3) Remove Records from Previous Month
# Clears the two rolling target datasets.
# -----------------------------------------------------------------------------
class RemovePreviousMonthRecords(object):
    def __init__(self):
        self.label = "Remove Records from Previous Month"
        self.description = "Delete rows from BioSpecies_Points and Bird_Nests_Points in WORKING.gdb."
        self.canRunInBackground = True

    def getParameterInfo(self):
        # No date needed; this model just truncates.
        return []

    def execute(self, parameters, messages):
        with arcpy.EnvManager(scratchWorkspace=WORKING_SCRATCH, workspace=WORKING_SCRATCH):
            _delete_rows(BIRD_NESTS_POINTS)
            _delete_rows(BIO_SPECIES_POINTS)
        arcpy.AddMessage("Previous month records removed.")


# -----------------------------------------------------------------------------
# (4) Append Joined BNPs and BSPs into Schema Datasets (V3)
# Same double-Append behavior as model #1; kept separate for parity with your
# four-model process naming.
# -----------------------------------------------------------------------------
class AppendJoinedBNPsAndBSPsV3(object):
    def __init__(self):
        self.label = "Append Joined BNPs and BSPs into Schema Datasets (V3)"
        self.description = "Append the prepared export tables into the schema datasets (NO_TEST field map)."
        self.canRunInBackground = True

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        with arcpy.EnvManager(scratchWorkspace=WORKING_SCRATCH, workspace=WORKING_SCRATCH):
            arcpy.AddMessage("Appending BioSpecies_Export → BioSpecies_Points ...")
            with arcpy.EnvManager(maintainAttachments=False, preserveGlobalIds=True):
                arcpy.management.Append(
                    inputs=[BIO_SPECIES_EXPORT],
                    target=BIO_SPECIES_POINTS,
                    schema_type="NO_TEST",
                    field_mapping=BSP_APPEND_FIELD_MAPPING
                )

            arcpy.AddMessage("Appending BirdNestPoints_Export → Bird_Nests_Points ...")
            with arcpy.EnvManager(maintainAttachments=False):
                arcpy.management.Append(
                    inputs=[BIRD_NESTPOINTS_EXPORT],
                    target=BIRD_NESTS_POINTS,
                    schema_type="NO_TEST",
                    field_mapping=BNP_APPEND_FIELD_MAPPING
                )

        arcpy.AddMessage("Append Joined BNPS/BSPs — complete.")
