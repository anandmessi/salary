import openpyxl
from database import upsert_worker, Worker

def import_employees(filepath='employee.xlsx'):
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        
        count = 0
        for row in ws.iter_rows(min_row=3, values_only=True):
            sl_no = row[0]
            name = row[1]
            ifsc = row[2]
            acct = row[3]
            
            # Skip empty rows
            if not sl_no or not name: 
                continue
                
            # Create a predictable ID like EMP001
            worker_id = f'EMP{int(sl_no):03d}' if isinstance(sl_no, (int, float)) else str(sl_no)
            
            w = Worker(
                worker_id=worker_id,
                name=str(name).strip(),
                ifsc_code=str(ifsc).strip() if ifsc else '',
                bank_account=str(acct).strip() if acct else '',
                skill_category='Unskilled',
                active=True
            )
            upsert_worker(w)
            count += 1

        print(f'Done! Successfully imported {count} workers from {filepath}.')
        
    except Exception as e:
        print(f"Error during import: {e}")

if __name__ == '__main__':
    import_employees()
