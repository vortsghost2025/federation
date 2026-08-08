#!/usr/bin/env python3
import sys, os
sys.path.insert(0, '/app')
os.environ['SPATIAL_ENABLED'] = 'true'
try:
    from spatial_seed import seed_spatial_system
    result = seed_spatial_system()
    print('SEED RESULT:', result)
except Exception as e:
    print('SEED ERROR:', e)
    import traceback
    traceback.print_exc()
