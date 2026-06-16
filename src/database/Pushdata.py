import pandas as pd
import mysql.connector
from mysql.connector import Error
from sqlalchemy import create_engine
import os
from pathlib import Path
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================================
# TiDB Connection Configuration
# Load from .env file
# ========================================
TIDB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 4000)),
    'user': os.getenv('DB_USERNAME'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_DATABASE'),
}

# ========================================
# Table Name Mappings
# Configure the mapping from file names/paths to table names
# ========================================
TABLE_MAPPINGS = {
    'population_southeast_2025.csv': 'population_southeast',
    'synthetic_tree_green_data_southeast_2025.csv': 'tree_green_data',
    'hcm_weather_2025.csv': 'weather_hcm',
    'VehicleCount.csv': 'vehicle_count',
    'traffic_ba_ria_vung_tau_2025.csv': 'traffic_ba_ria_vung_tau',
    'traffic_dong_nai_2025.csv': 'traffic_dong_nai',
    'traffic_ho_chi_minh_2025.csv': 'traffic_ho_chi_minh',
    'traffic_long_an_2025.csv': 'traffic_long_an',
    'traffic_tay_ninh_2025.csv': 'traffic_tay_ninh',
}

# ========================================
# Functions
# ========================================

def validate_config():
    """
    Validate that all required TiDB configuration is set
    """
    required_keys = ['DB_HOST', 'DB_USERNAME', 'DB_PASSWORD', 'DB_DATABASE']
    missing_keys = []
    
    for key in required_keys:
        if not os.getenv(key):
            missing_keys.append(key)
    
    if missing_keys:
        logger.error(f"Missing environment variables: {', '.join(missing_keys)}")
        logger.error("Please create a .env file with the required TiDB configuration")
        raise ValueError(f"Missing environment variables: {', '.join(missing_keys)}")
    
    logger.info("✅ All TiDB configuration variables found")

def get_tidb_engine():
    """
    Create SQLAlchemy engine for TiDB Cloud connection
    """
    try:
        connection_string = f"mysql+pymysql://{TIDB_CONFIG['user']}:{TIDB_CONFIG['password']}@{TIDB_CONFIG['host']}:{TIDB_CONFIG['port']}/{TIDB_CONFIG['database']}"
        engine = create_engine(connection_string)
        logger.info("Successfully created SQLAlchemy engine for TiDB Cloud")
        return engine
    except Exception as err:
        logger.error(f"Error creating engine for TiDB: {err}")
        raise

def get_csv_files(data_dir):
    """
    Recursively get all CSV files from the data/raw directory
    """
    csv_files = []
    for root, dirs, files in os.walk(data_dir):
        for file in files:
            if file.endswith('.csv'):
                csv_files.append(os.path.join(root, file))
    return csv_files

def get_table_name(file_path):
    """
    Get table name from file name using the mapping
    """
    file_name = os.path.basename(file_path)
    return TABLE_MAPPINGS.get(file_name, file_name.replace('.csv', '').replace('-', '_'))

def generate_create_table_sql(csv_file, table_name):
    """
    Generate CREATE TABLE SQL statement based on CSV file structure
    """
    try:
        df = pd.read_csv(csv_file, nrows=0)  # Read only headers
        
        # Clean column names
        columns = [col.replace(' ', '_').replace('-', '_').lower() for col in df.columns]
        
        # Create column definitions
        col_defs = []
        for col in columns:
            col_defs.append(f"    `{col}` VARCHAR(255)")
        
        col_defs_str = ',\n'.join(col_defs)
        create_sql = f"""CREATE TABLE IF NOT EXISTS `{table_name}` (
    id INT AUTO_INCREMENT PRIMARY KEY,
{col_defs_str},
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
        return create_sql
    except Exception as err:
        logger.error(f"Error generating SQL for {table_name}: {err}")
        return None

def push_csv_to_tidb_with_to_sql(engine, csv_file, table_name):
    """
    Read CSV file and push data to TiDB using pandas to_sql()
    """
    try:
        logger.info(f"Reading CSV file: {csv_file}")
        df = pd.read_csv(csv_file)
        
        # Clean column names
        df.columns = [col.replace(' ', '_').replace('-', '_').lower() for col in df.columns]
        
        logger.info(f"Writing {len(df)} rows to table `{table_name}`")
        
        # Use to_sql to insert data (assumes table exists)
        df.to_sql(
            table_name,
            con=engine,
            if_exists='append',
            index=False,
            chunksize=1000
        )
        
        logger.info(f"✅ Successfully pushed {len(df)} rows from {csv_file} to table `{table_name}`")
        
    except Exception as err:
        if "CREATE command denied" in str(err) or "doesn't exist" in str(err):
            logger.warning(f"⚠️  Table `{table_name}` does not exist or cannot be created due to permissions.")
            logger.warning(f"   Please have your TiDB administrator run the setup SQL script (setup_tables.sql)")
            logger.warning(f"   Then re-run this script to insert data.")
            return False
        else:
            logger.error(f"Error pushing data to {table_name}: {err}")
            raise
    return True

def push_all_data(data_dir):
    """
    Main function to push all CSV files from data/raw to TiDB
    """
    try:
        # Validate configuration
        validate_config()
        
        # Get engine
        engine = get_tidb_engine()
        
        # Get all CSV files
        csv_files = get_csv_files(data_dir)
        logger.info(f"Found {len(csv_files)} CSV files to process")
        
        # Generate setup SQL script
        setup_sql_path = os.path.join(os.path.dirname(data_dir), 'setup_tables.sql')
        with open(setup_sql_path, 'w') as f:
            f.write("-- TiDB Setup Script - Run this as admin/database owner\n")
            f.write("-- Execute this script to create all required tables\n\n")
            for csv_file in csv_files:
                table_name = get_table_name(csv_file)
                sql = generate_create_table_sql(csv_file, table_name)
                if sql:
                    f.write(sql + "\n")
        logger.info(f"📄 Setup SQL script generated at: {setup_sql_path}")
        logger.info("   Please have your TiDB administrator run this script first")
        
        # Process each file
        successful = 0
        failed = 0
        for csv_file in csv_files:
            table_name = get_table_name(csv_file)
            logger.info(f"\nProcessing: {csv_file} -> Table: {table_name}")
            
            # Try to push data
            if push_csv_to_tidb_with_to_sql(engine, csv_file, table_name):
                successful += 1
            else:
                failed += 1
        
        engine.dispose()
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing complete: {successful} successful, {failed} failed")
        logger.info(f"Setup script: {setup_sql_path}")
        logger.info(f"{'='*60}")
        
    except Exception as err:
        logger.error(f"Error: {err}")

if __name__ == "__main__":
    # Get the project root directory
    current_dir = Path(__file__).parent.parent.parent
    data_raw_dir = os.path.join(current_dir, 'data', 'raw')
    
    logger.info(f"Starting data push to TiDB from: {data_raw_dir}")
    push_all_data(data_raw_dir)
