"""
inspect_ehr_db.py — Inspect EHR records stored in the local database.

Shows connection status, record counts by type, and sample records.

Usage:
    cd backend
    python scripts/inspect_ehr_db.py
    python scripts/inspect_ehr_db.py --patient-id patient-demo-001
    python scripts/inspect_ehr_db.py --resource-type Condition
    python scripts/inspect_ehr_db.py --patient-id patient-demo-001 --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import get_session
from app.db.models import EHRRecordRow, EHRConnectionRow
from sqlalchemy import func


def show_connections(patient_id: str | None = None):
    """Display EHR connection status for all or specific patient."""
    print("=" * 60)
    print("EHR CONNECTIONS")
    print("=" * 60)
    
    with get_session() as session:
        query = session.query(EHRConnectionRow)
        if patient_id:
            query = query.filter_by(patient_id=patient_id)
        
        connections = query.all()
        
        if not connections:
            if patient_id:
                print(f"No connection found for patient: {patient_id}")
            else:
                print("No EHR connections found in database.")
            return
        
        for conn in connections:
            print(f"\nPatient ID: {conn.patient_id}")
            print(f"  Status: {conn.connection_status}")
            print(f"  Connected at: {conn.connected_at or 'N/A'}")
            print(f"  Last synced: {conn.last_synced_at or 'N/A'}")
            print(f"  Resource counts:")
            if conn.fhir_resource_counts:
                for resource_type, count in conn.fhir_resource_counts.items():
                    print(f"    - {resource_type}: {count}")
            else:
                print("    (none)")


def show_record_counts(patient_id: str | None = None, resource_type: str | None = None):
    """Display record counts grouped by type."""
    print("\n" + "=" * 60)
    print("RECORD COUNTS BY TYPE")
    print("=" * 60)
    
    with get_session() as session:
        query = session.query(
            EHRRecordRow.resource_type, 
            func.count(EHRRecordRow.id)
        )
        
        if patient_id:
            query = query.filter(EHRRecordRow.patient_id == patient_id)
        if resource_type:
            query = query.filter(EHRRecordRow.resource_type == resource_type)
        
        counts = query.group_by(EHRRecordRow.resource_type).all()
        
        if not counts:
            print("No records found.")
            return
        
        total = 0
        for r_type, count in counts:
            print(f"  {r_type:25} {count:5} records")
            total += count
        
        print(f"\n  {'TOTAL':25} {total:5} records")


def show_sample_records(
    patient_id: str | None = None, 
    resource_type: str | None = None,
    limit: int = 5
):
    """Display sample records with details."""
    print("\n" + "=" * 60)
    print(f"SAMPLE RECORDS (limit: {limit})")
    print("=" * 60)
    
    with get_session() as session:
        query = session.query(EHRRecordRow)
        
        if patient_id:
            query = query.filter(EHRRecordRow.patient_id == patient_id)
        if resource_type:
            query = query.filter(EHRRecordRow.resource_type == resource_type)
        
        records = query.order_by(EHRRecordRow.synced_at.desc()).limit(limit).all()
        
        if not records:
            print("No records found.")
            return
        
        for idx, rec in enumerate(records, 1):
            print(f"\n[{idx}] {rec.resource_type} — {rec.resource_id}")
            print(f"    Patient: {rec.patient_id}")
            print(f"    Synced: {rec.synced_at}")
            
            # Pretty print relevant fields from the FHIR resource
            data = rec.resource_json or {}
            
            if rec.resource_type == "Condition":
                code = data.get("code", {})
                text = code.get("text") or (
                    code.get("coding", [{}])[0].get("display", "")
                )
                status = data.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "")
                print(f"    Condition: {text}")
                print(f"    Status: {status}")
            
            elif rec.resource_type == "Observation":
                code = data.get("code", {})
                text = code.get("text") or (
                    code.get("coding", [{}])[0].get("display", "")
                )
                value = data.get("valueQuantity", {})
                if value:
                    print(f"    Observation: {text}")
                    print(f"    Value: {value.get('value')} {value.get('unit', '')}")
                else:
                    value_str = data.get("valueString", "")
                    print(f"    Observation: {text}")
                    if value_str:
                        print(f"    Value: {value_str}")
            
            elif rec.resource_type == "MedicationRequest":
                med = data.get("medicationCodeableConcept", {})
                text = med.get("text") or (
                    med.get("coding", [{}])[0].get("display", "")
                )
                status = data.get("status", "")
                print(f"    Medication: {text}")
                print(f"    Status: {status}")
            
            elif rec.resource_type == "AllergyIntolerance":
                code = data.get("code", {})
                text = code.get("text") or (
                    code.get("coding", [{}])[0].get("display", "")
                )
                reaction = data.get("reaction", [{}])[0].get("manifestation", [{}])[0].get("text", "")
                print(f"    Allergy: {text}")
                if reaction:
                    print(f"    Reaction: {reaction}")
            
            elif rec.resource_type == "Encounter":
                type_info = data.get("type", [{}])[0]
                text = type_info.get("text") or (
                    type_info.get("coding", [{}])[0].get("display", "")
                )
                status = data.get("status", "")
                period = data.get("period", {})
                print(f"    Type: {text}")
                print(f"    Status: {status}")
                if period.get("start"):
                    print(f"    Start: {period['start']}")


def show_full_record_json(
    patient_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None
):
    """Display full JSON for one record."""
    print("\n" + "=" * 60)
    print("FULL RECORD JSON")
    print("=" * 60)
    
    with get_session() as session:
        query = session.query(EHRRecordRow)
        
        if patient_id:
            query = query.filter(EHRRecordRow.patient_id == patient_id)
        if resource_type:
            query = query.filter(EHRRecordRow.resource_type == resource_type)
        if resource_id:
            query = query.filter(EHRRecordRow.resource_id == resource_id)
        
        record = query.first()
        
        if not record:
            print("No record found matching criteria.")
            return
        
        print(f"\nResource ID: {record.resource_id}")
        print(f"Type: {record.resource_type}")
        print(f"Patient: {record.patient_id}")
        print(f"Synced: {record.synced_at}\n")
        print(json.dumps(record.resource_json, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Inspect EHR records in local database")
    parser.add_argument(
        "--patient-id",
        help="Filter by patient ID"
    )
    parser.add_argument(
        "--resource-type",
        choices=["Condition", "Observation", "MedicationRequest", "AllergyIntolerance", "Encounter"],
        help="Filter by resource type"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of sample records to show (default: 5)"
    )
    parser.add_argument(
        "--resource-id",
        help="Show full JSON for specific resource ID (requires --patient-id)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Show full JSON for first matching record"
    )
    
    args = parser.parse_args()
    
    if args.resource_id and args.json:
        show_full_record_json(
            patient_id=args.patient_id,
            resource_type=args.resource_type,
            resource_id=args.resource_id
        )
    elif args.json:
        show_full_record_json(
            patient_id=args.patient_id,
            resource_type=args.resource_type
        )
    else:
        # Normal inspection flow
        show_connections(args.patient_id)
        show_record_counts(args.patient_id, args.resource_type)
        show_sample_records(args.patient_id, args.resource_type, args.limit)
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
