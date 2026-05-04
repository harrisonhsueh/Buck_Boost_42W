import pandas as pd
from typing import Dict

def get_inductor_specs(part_number: str, csv_path: str = "data/inductors.csv") -> Dict:
    """Queries the database and returns a dictionary of part specs."""
    df = pd.read_csv(csv_path)
    # Ensure Part_Number is treated as a string for comparison
    row = df[df['Part_Number'].astype(str) == str(part_number)]
    
    if row.empty:
        raise ValueError(f"Part {part_number} not found in {csv_path}")
    
    return row.iloc[0].to_dict()

def get_component_specs(part_number: str, csv_path: str):
    """Generic loader that cleans headers for easier access."""
    df = pd.read_csv(csv_path)
    # Remove units and special chars from headers for cleaner dict keys
    # e.g., 'RDSon_4.5V_Max(mOhm)' becomes 'RDSon_4.5V_Max'
    df.columns = [c.split('(')[0].strip() for c in df.columns]
    
    row = df[df['Part_Number'].astype(str) == str(part_number)]
    if row.empty:
        raise ValueError(f"Part {part_number} not found in {csv_path}")
    
    return row.iloc[0].to_dict()