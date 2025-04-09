import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid

def maak_dicom_sr_layout(
    # Algemeen
    instance_creation_date, instance_creation_time, study_date, series_date, content_date,
    study_time, series_time, content_time, accession_number, modality, conversion_type,
    manufacturer, station_name, study_description, series_description,
    
    # ContentSequence
    concept_code_1, code_value_1, code_meaning_1, text_value_1,
    concept_code_2, code_value_2, code_meaning_2, text_value_2,
    concept_code_3, code_value_3, code_meaning_3, text_value_3,
    concept_code_4, code_value_4, code_meaning_4, text_value_4,
    concept_code_5, code_value_5, code_meaning_5, text_value_5,

    # Presentation
    content_label, content_description, presentation_creation_date, presentation_creation_time, content_creator_name,
    
    # Identifiers
    study_instance_uid, series_instance_uid, study_id, series_number, instance_number, requested_procedure_id
):
    # Maak een nieuw DICOM SR-bestand (Structured Report)
    sr = Dataset()

    # Algemene DICOM tags
    sr.SpecificCharacterSet = "ISO_IR 100"
    sr.InstanceCreationDate = instance_creation_date
    sr.InstanceCreationTime = instance_creation_time
    sr.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    sr.SOPInstanceUID = generate_uid()
    sr.StudyDate = study_date
    sr.SeriesDate = series_date
    sr.ContentDate = content_date
    sr.StudyTime = study_time
    sr.SeriesTime = series_time
    sr.ContentTime = content_time
    sr.AccessionNumber = accession_number
    sr.Modality = modality
    sr.ConversionType = conversion_type
    sr.Manufacturer = manufacturer  # Dynamisch ingevulde variabele
    sr.ReferringPhysicianName = ""
    sr.StationName = station_name  # Dynamisch ingevulde variabele
    sr.StudyDescription = study_description  # Dynamisch ingevulde variabele
    sr.SeriesDescription = series_description
    
    # Identifiers
    sr.StudyInstanceUID = study_instance_uid
    sr.SeriesInstanceUID = series_instance_uid
    sr.StudyID = study_id
    sr.SeriesNumber = series_number
    sr.InstanceNumber = instance_number
    sr.RequestedProcedureID = requested_procedure_id

    # ContentSequence
    content_sequence = []

    # Voeg relatie en waarde-type elementen toe
    def add_text_value(concept_code, code_value, code_meaning, text_value):
        element = Dataset()
        element.RelationshipType = "CONTAINS"
        element.ValueType = "TEXT"
        element.ConceptNameCodeSequence = [Dataset()]
        element.ConceptNameCodeSequence[0].CodeValue = code_value
        element.ConceptNameCodeSequence[0].CodingSchemeDesignator = "DCM" if code_value != "74019-1" else "LN"
        element.ConceptNameCodeSequence[0].CodeMeaning = code_meaning
        element.TextValue = text_value
        content_sequence.append(element)

    # Voeg de verschillende elementen toe aan de ContentSequence
    add_text_value(concept_code_1, code_value_1, code_meaning_1, text_value_1)
    add_text_value(concept_code_2, code_value_2, code_meaning_2, text_value_2)
    add_text_value(concept_code_3, code_value_3, code_meaning_3, text_value_3)
    add_text_value(concept_code_4, code_value_4, code_meaning_4, text_value_4)
    add_text_value(concept_code_5, code_value_5, code_meaning_5, text_value_5)

    sr.ContentSequence = content_sequence

    # Presentation information
    sr.ContentLabel = content_label
    sr.ContentDescription = content_description
    sr.PresentationCreationDate = presentation_creation_date
    sr.PresentationCreationTime = presentation_creation_time
    sr.ContentCreatorName = content_creator_name

    # Sla het DICOM SR-bestand op
    sr.save_as("voorbeeld_dicom_sr_layout_with_dynamic_variables.dcm")

if __name__ == "__main__":
    # Voorbeeld van variabelen die je kunt aanpassen
    manufacturer = "Aidoc"  # Dynamische variabele
    station_name = "RAD2106168"  # Dynamische variabele
    study_description = "CTA pulmonalis"  # Dynamische variabele
    
    maak_dicom_sr_layout(
        instance_creation_date="20250407", instance_creation_time="152047", 
        study_date="20250407", series_date="20250407", content_date="20250407",
        study_time="151313.648", series_time="152047", content_time="152047", 
        accession_number="5004182070", modality="SR", conversion_type="SYN",
        manufacturer=manufacturer, station_name=station_name, study_description=study_description, 
        series_description="Aidoc-PE",
        
        # ContentSequence (vul de variabelen in voor de secties)
        concept_code_1="121013", code_value_1="121013", code_meaning_1="Observer", text_value_1="PE",
        concept_code_2="18782-3", code_value_2="18782-3", code_meaning_2="Findings", text_value_2="PE",
        concept_code_3="19005-8", code_value_3="19005-8", code_meaning_3="Conclusion", text_value_3="Has Pulmonary Embolism",
        concept_code_4="74019-1", code_value_4="74019-1", code_meaning_4="Likelihood", text_value_4="1.0",
        concept_code_5="LA12748-2", code_value_5="LA12748-2", code_meaning_5="Binary answer", text_value_5="1",
        
        # Presentation info
        content_label="PE", content_description="Pulmonary Embolism", 
        presentation_creation_date="20250407", presentation_creation_time="132037", 
        content_creator_name="Aidoc",
        
        # Identifiers
        study_instance_uid="1.2.826.0.1.5968184.2.2.1.1742324812119.28438", 
        series_instance_uid="1.2.826.0.1.3680043.9.6883.1.29902560993579461309719870404490308", 
        study_id="4003854332", series_number="9899", instance_number="1", requested_procedure_id="4003854332"
    )
