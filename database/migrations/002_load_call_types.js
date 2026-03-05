exports.up = async (pool) => {
    const callTypes = require('../../all_call_types_combined.json');
    
    for (const ct of callTypes) {
      await pool.query(`
        INSERT INTO merged_call_types (
          "Category",
          "Call Type Code_NEW",
          "Short Description-Call Type",
          "Dept/MOE & Call Type"
        ) VALUES ($1, $2, $3, $4)
        ON CONFLICT ("Category", "Call Type Code_NEW") DO UPDATE SET
          "Short Description-Call Type" = EXCLUDED."Short Description-Call Type",
          "Dept/MOE & Call Type" = EXCLUDED."Dept/MOE & Call Type"
      `, [
        ct.intent_bucket || ct.department?.toLowerCase() || 'general',
        ct.call_type_code,
        ct.short_description,
        ct.department
      ]);
    }
    
    console.log(`Loaded ${callTypes.length} call types`);
  };