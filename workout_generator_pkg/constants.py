"""Large constant definitions for workout generator."""

import json

JSON_SCHEMA = {                                                                                                                                                                                                                                  
    "$schema": "https://json-schema.org/draft/2020-12/schema",                                                                                                                                                                                   
    "title": "WorkoutStore",                                                                                                                                                                                                                     
    "type": "object",                                                                                                                                                                                                                            
    "additionalProperties": False,                                                                                                                                                                                                               
    "required": [                                                                                                                                                                                                                                
        "workouts",                                                                                                                                                                                                                              
        "equipments",                                                                                                                                                                                                                            
        "birthDateYear",                                                                                                                                                                                                                         
        "weightKg",                                                                                                                                                                                                                              
        "progressionPercentageAmount"                                                                                                                                                                                                            
    ],
    "properties": {                                                                                                                                                                                                                              
        "workouts": {"type": "array", "items": {"$ref": "#/$defs/Workout"}},                                                                                                                                                                    
        "equipments": {"type": "array", "items": {"$ref": "#/$defs/Equipment"}},                                                                                                                                                                
        "accessoryEquipments": {"type": "array", "items": {"$ref": "#/$defs/EquipmentAccessory"}},
        "polarDeviceId": {"type": ["string", "null"]},                                                                                                                                                                                           
        "birthDateYear": {"type": "integer"},
        "weightKg": {"type": "number"},                                                                                                                                                                                                          
        "progressionPercentageAmount": {"type": "number"}                                                                                                                                                                                        
    },
    "$defs": {                                                                                                                                                                                                                                   
        "UUID": {                                                                                                                                                                                                                                
            "type": "string",                                                                                                                                                                                                                    
            "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"                                                                                                                                           
        },                                                                                                                                                                                                                                       
        "LocalDate": {                                                                                                                                                                                                                           
            "type": "string",                                                                                                                                                                                                                    
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"                                                                                                                                                                                                  
        },                                                                                                                                                                                                                                       
        "SetSubCategory": {                                                                                                                                                                                                                      
            "type": "string",                                                                                                                                                                                                                    
            "enum": ["WorkSet", "WarmupSet", "RestPauseSet", "BackOffSet"]
        },                                                                                                                                                                                                                                       
        "ExerciseType": {                                                                                                                                                                                                                        
            "type": "string",                                                                                                                                                                                                                    
            "enum": ["COUNTUP", "BODY_WEIGHT", "COUNTDOWN", "WEIGHT"]                                                                                                                                                                            
        },                                                                                                                                                                                                                                       
        "ExerciseCategory": {
            "type": "string",
            "enum": ["HEAVY_COMPOUND", "MODERATE_COMPOUND", "ISOLATION"]
        },
        "MuscleGroup": {                                                                                                                                                                                                                         
            "type": "string",                                                                                                                                                                                                                    
            "enum": [                                                                                                                                                                                                                            
                "FRONT_ABS",                                                                                                                                                                                                                     
                "FRONT_ADDUCTORS",                                                                                                                                                                                                               
                "FRONT_ANKLES",                                                                                                                                                                                                                  
                "FRONT_BICEPS",                                                                                                                                                                                                                  
                "FRONT_CALVES",                                                                                                                                                                                                                  
                "FRONT_CHEST",                                                                                                                                                                                                                   
                "FRONT_DELTOIDS",
                "FRONT_FEET",                                                                                                                                                                                                                    
                "FRONT_FOREARM",                                                                                                                                                                                                                 
                "FRONT_HANDS",                                                                                                                                                                                                                   
                "FRONT_KNEES",                                                                                                                                                                                                                   
                "FRONT_NECK",                                                                                                                                                                                                                    
                "FRONT_OBLIQUES",                                                                                                                                                                                                                
                "FRONT_QUADRICEPS",                                                                                                                                                                                                              
                "FRONT_TIBIALIS",                                                                                                                                                                                                                
                "FRONT_TRAPEZIUS",                                                                                                                                                                                                               
                "FRONT_TRICEPS",                                                                                                                                                                                                                 
                "BACK_ADDUCTORS",                                                                                                                                                                                                                
                "BACK_ANKLES",                                                                                                                                                                                                                   
                "BACK_CALVES",                                                                                                                                                                                                                   
                "BACK_DELTOIDS",                                                                                                                                                                                                                 
                "BACK_FEET",                                                                                                                                                                                                                     
                "BACK_FOREARM",                                                                                                                                                                                                                  
                "BACK_GLUTEAL",                                                                                                                                                                                                                  
                "BACK_HAMSTRING",                                                                                                                                                                                                                
                "BACK_HANDS",                                                                                                                                                                                                                    
                "BACK_LOWER_BACK",                                                                                                                                                                                                               
                "BACK_NECK",                                                                                                                                                                                                                     
                "BACK_TRAPEZIUS",                                                                                                                                                                                                                
                "BACK_TRICEPS",                                                                                                                                                                                                                  
                "BACK_UPPER_BACK"                                                                                                                                                                                                                
            ]                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "BaseWeight": {                                                                                                                                                                                                                          
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["weight"],                                                                                                                                                                                                              
            "properties": {"weight": {"type": "number"}}                                                                                                                                                                                         
        },                                                                                                                                                                                                                                       
        # Plate: thickness is in millimeters (mm)
        "Plate": {
            "type": "object",
            "additionalProperties": False,
            "required": ["weight", "thickness"],
            "properties": {
                "weight": {"type": "number"},
                "thickness": {"type": "number"}  # in millimeters (mm)
            }
        },
        "WeightSet": {                                                                                                                                                                                                                           
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "reps", "weight", "subCategory"],                                                                                                                                                                         
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "WeightSet"},                                                                                                                                                                                                  
                "reps": {"type": "integer"},                                                                                                                                                                                                     
                "weight": {"type": "number"},                                                                                                                                                                                                    
                "subCategory": {"$ref": "#/$defs/SetSubCategory"}                                                                                                                                                                                
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "BodyWeightSet": {                                                                                                                                                                                                                       
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "reps", "additionalWeight", "subCategory"],                                                                                                                                                               
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "BodyWeightSet"},                                                                                                                                                                                              
                "reps": {"type": "integer"},                                                                                                                                                                                                     
                "additionalWeight": {"type": "number"},                                                                                                                                                                                          
                "subCategory": {"$ref": "#/$defs/SetSubCategory"}
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "TimedDurationSet": {                                                                                                                                                                                                                    
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "timeInMillis", "autoStart", "autoStop"],                                                                                                                                                                 
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "TimedDurationSet"},                                                                                                                                                                                           
                "timeInMillis": {"type": "integer"},                                                                                                                                                                                             
                "autoStart": {"type": "boolean"},                                                                                                                                                                                                
                "autoStop": {"type": "boolean"}                                                                                                                                                                                                  
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "EnduranceSet": {                                                                                                                                                                                                                        
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "timeInMillis", "autoStart", "autoStop"],                                                                                                                                                                 
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "EnduranceSet"},                                                                                                                                                                                               
                "timeInMillis": {"type": "integer"},                                                                                                                                                                                             
                "autoStart": {"type": "boolean"},                                                                                                                                                                                                
                "autoStop": {"type": "boolean"}                                                                                                                                                                                                  
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "RestSet": {                                                                                                                                                                                                                             
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "timeInSeconds", "subCategory"],                                                                                                                                                                          
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "RestSet"},                                                                                                                                                                                                    
                "timeInSeconds": {"type": "integer"},                                                                                                                                                                                            
                "subCategory": {"$ref": "#/$defs/SetSubCategory"}                                                                                                                                                                                
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Set": {                                                                                                                                                                                                                                 
            "oneOf": [                                                                                                                                                                                                                           
                {"$ref": "#/$defs/WeightSet"},                                                                                                                                                                                                   
                {"$ref": "#/$defs/BodyWeightSet"},                                                                                                                                                                                               
                {"$ref": "#/$defs/TimedDurationSet"},                                                                                                                                                                                            
                {"$ref": "#/$defs/EnduranceSet"},                                                                                                                                                                                                
                {"$ref": "#/$defs/RestSet"}                                                                                                                                                                                                      
            ]                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Exercise": {                                                                                                                                                                                                                            
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "enabled",                                                                                                                                                                                                                       
                "name",                                                                                                                                                                                                                          
                "doNotStoreHistory",                                                                                                                                                                                                             
                "notes",                                                                                                                                                                                                                         
                "sets",                                                                                                                                                                                                                          
                "exerciseType",                                                                                                                                                                                                                  
                "minLoadPercent",                                                                                                                                                                                                                
                "maxLoadPercent",                                                                                                                                                                                                                
                "minReps",                                                                                                                                                                                                                       
                "maxReps",                                                                                                                                                                                                                       
                "generateWarmUpSets",                                                                                                                                                                                                            
                "enableProgression",                                                                                                                                                                                                             
                "keepScreenOn",                                                                                                                                                                                                                  
                "showCountDownTimer"                                                                                                                                                                                                             
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "Exercise"},                                                                                                                                                                                                   
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "name": {"type": "string"},                                                                                                                                                                                                      
                "doNotStoreHistory": {"type": "boolean"},                                                                                                                                                                                        
                "notes": {"type": "string", "maxLength": 500},                                                                                                                                                                                                     
                "sets": {"type": "array", "items": {"$ref": "#/$defs/Set"}},                                                                                                                                                                     
                "exerciseType": {"$ref": "#/$defs/ExerciseType"},                                                                                                                                                                                
                "minLoadPercent": {"type": "number"},                                                                                                                                                                                            
                "maxLoadPercent": {"type": "number"},                                                                                                                                                                                            
                "minReps": {"type": "integer"},                                                                                                                                                                                                  
                "maxReps": {"type": "integer"},                                                                                                                                                                                                  
                "lowerBoundMaxHRPercent": {"type": ["number", "null"]},                                                                                                                                                                          
                "upperBoundMaxHRPercent": {"type": ["number", "null"]},                                                                                                                                                                          
                "equipmentId": {                                                                                                                                                                                                                 
                    "anyOf": [                                                                                                                                                                                                                   
                        {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                
                        {"type": "null"}                                                                                                                                                                                                         
                    ]                                                                                                                                                                                                                            
                },                                                                                                                                                                                                                               
                "bodyWeightPercentage": {"type": ["number", "null"]},                                                                                                                                                                            
                "generateWarmUpSets": {"type": "boolean"},                                                                                                                                                                                       
                "enableProgression": {"type": "boolean"},                                                                                                                                                                                        
                "keepScreenOn": {"type": "boolean"},                                                                                                                                                                                             
                "showCountDownTimer": {"type": "boolean"},                                                                                                                                                                                       
                "intraSetRestInSeconds": {"type": ["integer", "null"]},                                                                                                                                                                          
                "loadJumpDefaultPct": {"type": ["number", "null"]},                                                                                                                                                                              
                "loadJumpMaxPct": {"type": ["number", "null"]},                                                                                                                                                                                  
                "loadJumpOvercapUntil": {"type": ["integer", "null"]},                                                                                                                                                                           
                "muscleGroups": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/MuscleGroup"},
                    "uniqueItems": True,
                    "minItems": 1
                },
                "secondaryMuscleGroups": {                                                                                                                                                                                                       
                    "type": "array",                                                                                                                                                                                                             
                    "items": {"$ref": "#/$defs/MuscleGroup"},                                                                                                                                                                                    
                    "uniqueItems": True                                                                                                                                                                                                          
                },
                "requiredAccessoryEquipmentIds": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/UUID"},
                    "uniqueItems": True
                },
                "requiresLoadCalibration": {"type": "boolean"},
                "exerciseCategory": {
                    "oneOf": [
                        {"$ref": "#/$defs/ExerciseCategory"},
                        {"type": "null"}
                    ]
                }
            }                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "RestComponent": {
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "enabled", "timeInSeconds"],                                                                                                                                                                              
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "Rest"},                                                                                                                                                                                                       
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "timeInSeconds": {"type": "integer"}                                                                                                                                                                                             
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Superset": {                                                                                                                                                                                                                            
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "enabled", "exercises", "restSecondsByExercise"],                                                                                                                                                         
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "Superset"},                                                                                                                                                                                                   
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "exercises": {"type": "array", "items": {"$ref": "#/$defs/Exercise"}},                                                                                                                                                           
                "restSecondsByExercise": {                                                                                                                                                                                                       
                    "type": "object",                                                                                                                                                                                                            
                    "additionalProperties": {"type": "integer"}                                                                                                                                                                                  
                }                                                                                                                                                                                                                                
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "WorkoutComponent": {                                                                                                                                                                                                                    
            "oneOf": [                                                                                                                                                                                                                           
                {"$ref": "#/$defs/Exercise"},                                                                                                                                                                                                    
                {"$ref": "#/$defs/RestComponent"},                                                                                                                                                                                               
                {"$ref": "#/$defs/Superset"}                                                                                                                                                                                                     
            ]                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Workout": {                                                                                                                                                                                                                             
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "name",                                                                                                                                                                                                                          
                "description",                                                                                                                                                                                                                   
                "workoutComponents",                                                                                                                                                                                                             
                "order",                                                                                                                                                                                                                         
                "enabled",                                                                                                                                                                                                                       
                "usePolarDevice",                                                                                                                                                                                                                
                "creationDate",                                                                                                                                                                                                                  
                "isActive",                                                                                                                                                                                                                      
                "globalId",                                                                                                                                                                                                                      
                "type"                                                                                                                                                                                                                           
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "name": {"type": "string"},                                                                                                                                                                                                      
                "description": {"type": "string", "maxLength": 50},                                                                                                                                                                                               
                "workoutComponents": {
                    "type": "array",
                    "items": {
                        "allOf": [
                            {"not": {"type": "null"}},
                            {"oneOf": [
                                {"$ref": "#/$defs/Exercise"},
                                {"$ref": "#/$defs/RestComponent"},
                                {"$ref": "#/$defs/Superset"}
                            ]}
                        ]
                    }
                },
                "order": {"type": "integer"},                                                                                                                                                                                                    
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "usePolarDevice": {"type": "boolean"},                                                                                                                                                                                           
                "creationDate": {"$ref": "#/$defs/LocalDate"},                                                                                                                                                                                   
                "previousVersionId": {                                                                                                                                                                                                           
                    "anyOf": [                                                                                                                                                                                                                   
                        {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                
                        {"type": "null"}                                                                                                                                                                                                         
                    ]                                                                                                                                                                                                                            
                },                                                                                                                                                                                                                               
                "nextVersionId": {                                                                                                                                                                                                               
                    "anyOf": [                                                                                                                                                                                                                   
                        {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                
                        {"type": "null"}                                                                                                                                                                                                         
                    ]                                                                                                                                                                                                                            
                },                                                                                                                                                                                                                               
                "isActive": {"type": "boolean"},                                                                                                                                                                                                 
                "timesCompletedInAWeek": {"type": ["integer", "null"]},                                                                                                                                                                          
                "globalId": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                            
                "type": {"type": "integer"}                                                                                                                                                                                                      
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        # EquipmentBarbell: sleeveLength is in millimeters (mm) - refers to sleeve length (where plates are loaded), not total barbell length
        "EquipmentBarbell": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name", "availablePlates", "barWeight"],
            "anyOf": [{"required": ["sleeveLength"]}, {"required": ["barLength"]}],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "BARBELL"},
                "name": {"type": "string"},
                "availablePlates": {"type": "array", "items": {"$ref": "#/$defs/Plate"}},
                "barWeight": {"type": "number"},
                "sleeveLength": {"type": "integer"},  # in millimeters (mm)
                "barLength": {"type": "integer"}  # deprecated alias for sleeveLength
            }
        },
        "EquipmentDumbbells": {                                                                                                                                                                                                                  
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "name",                                                                                                                                                                                                                          
                "maxExtraWeightsPerLoadingPoint",                                                                                                                                                                                                
                "extraWeights",                                                                                                                                                                                                                  
                "dumbbells"                                                                                                                                                                                                                      
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "DUMBBELLS"},                                                                                                                                                                                                  
                "name": {"type": "string"},                                                                                                                                                                                                      
                "maxExtraWeightsPerLoadingPoint": {"type": "integer"},                                                                                                                                                                           
                "extraWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}},                                                                                                                                                      
                "dumbbells": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "EquipmentDumbbell": {                                                                                                                                                                                                                   
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "name",                                                                                                                                                                                                                          
                "maxExtraWeightsPerLoadingPoint",                                                                                                                                                                                                
                "extraWeights",                                                                                                                                                                                                                  
                "dumbbells"                                                                                                                                                                                                                      
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "DUMBBELL"},                                                                                                                                                                                                   
                "name": {"type": "string"},                                                                                                                                                                                                      
                "maxExtraWeightsPerLoadingPoint": {"type": "integer"},                                                                                                                                                                           
                "extraWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}},                                                                                                                                                      
                "dumbbells": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}                                                                                                                                                          
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        # EquipmentPlateLoadedCable: sleeveLength is in millimeters (mm) - refers to sleeve length (where plates are loaded)
        "EquipmentPlateLoadedCable": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name", "availablePlates"],
            "anyOf": [{"required": ["sleeveLength"]}, {"required": ["barLength"]}],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "PLATELOADEDCABLE"},
                "name": {"type": "string"},
                "availablePlates": {"type": "array", "items": {"$ref": "#/$defs/Plate"}},
                "sleeveLength": {"type": "integer"},  # in millimeters (mm)
                "barLength": {"type": "integer"}  # deprecated alias for sleeveLength
            }
        },
        "EquipmentWeightVest": {                                                                                                                                                                                                                 
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "name", "availableWeights"],                                                                                                                                                                              
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "WEIGHTVEST"},                                                                                                                                                                                                 
                "name": {"type": "string"},                                                                                                                                                                                                      
                "availableWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}                                                                                                                                                   
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "EquipmentMachine": {                                                                                                                                                                                                                    
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "name",                                                                                                                                                                                                                          
                "availableWeights",                                                                                                                                                                                                              
                "maxExtraWeightsPerLoadingPoint",
                "extraWeights"                                                                                                                                                                                                                   
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "MACHINE"},                                                                                                                                                                                                    
                "name": {"type": "string"},                                                                                                                                                                                                      
                "availableWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}},                                                                                                                                                  
                "maxExtraWeightsPerLoadingPoint": {"type": "integer"},                                                                                                                                                                           
                "extraWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}                                                                                                                                                       
            }                                                                                                                                                                                                                                    
        },
        "EquipmentAccessory": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name"],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "ACCESSORY"},
                "name": {"type": "string"}
            }
        },
        "Equipment": {
            "oneOf": [
                {"$ref": "#/$defs/EquipmentBarbell"},
                {"$ref": "#/$defs/EquipmentDumbbells"},                                                                                                                                                                                          
                {"$ref": "#/$defs/EquipmentDumbbell"},                                                                                                                                                                                           
                {"$ref": "#/$defs/EquipmentPlateLoadedCable"},                                                                                                                                                                                   
                {"$ref": "#/$defs/EquipmentWeightVest"},                                                                                                                                                                                         
                {"$ref": "#/$defs/EquipmentMachine"}                                                                                                                                                                                             
            ]                                                                                                                                                                                                                                    
        }                                                                                                                                                                                                                                        
    }                                                                                                                                                                                                                                            
}                                                                                                                                                                                                                                                
EXAMPLE_JSON = {                                                                                                                                                                                                                                 
    "workouts": [
        {                                                                                                                                                                                                                                        
            "id": "11111111-1111-1111-1111-111111111111",                                                                                                                                                                                        
            "name": "Example Workout",                                                                                                                                                                                                           
            "description": "Example description",                                                                                                                                                                                                
            "workoutComponents": [                                                                                                                                                                                                               
                {                                                                                                                                                                                                                                
                    "id": "22222222-2222-2222-2222-222222222222",                                                                                                                                                                                
                    "type": "Exercise",                                                                                                                                                                                                          
                    "enabled": True,                                                                                                                                                                                                             
                    "name": "Back Squat",                                                                                                                                                                                                        
                    "doNotStoreHistory": False,                                                                                                                                                                                                  
                    "notes": "",
                    "sets": [                                                                                                                                                                                                                    
                        {                                                                                                                                                                                                                        
                            "id": "33333333-3333-3333-3333-333333333333",                                                                                                                                                                        
                            "type": "WeightSet",                                                                                                                                                                                                 
                            "reps": 5,                                                                                                                                                                                                           
                            "weight": 100.0,                                                                                                                                                                                                     
                            "subCategory": "WorkSet"                                                                                                                                                                                             
                        },                                                                                                                                                                                                                       
                        {                                                                                                                                                                                                                        
                            "id": "44444444-4444-4444-4444-444444444444",                                                                                                                                                                        
                            "type": "RestSet",                                                                                                                                                                                                   
                            "timeInSeconds": 120,                                                                                                                                                                                                
                            "subCategory": "WorkSet"                                                                                                                                                                                             
                        }                                                                                                                                                                                                                        
                    ],                                                                                                                                                                                                                           
                    "exerciseType": "WEIGHT",                                                                                                                                                                                                    
                    "minLoadPercent": 0.0,                                                                                                                                                                                                       
                    "maxLoadPercent": 0.0,                                                                                                                                                                                                       
                    "minReps": 5,                                                                                                                                                                                                                
                    "maxReps": 5,                                                                                                                                                                                                                
                    "lowerBoundMaxHRPercent": None,                                                                                                                                                                                              
                    "upperBoundMaxHRPercent": None,                                                                                                                                                                                              
                    "equipmentId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",                                                                                                                                                                       
                    "bodyWeightPercentage": None,                                                                                                                                                                                                
                    "generateWarmUpSets": False,                                                                                                                                                                                                 
                    "enableProgression": False,                                                                                                                                                                                                  
                    "keepScreenOn": False,                                                                                                                                                                                                       
                    "showCountDownTimer": False,                                                                                                                                                                                                 
                    "intraSetRestInSeconds": None,                                                                                                                                                                                               
                    "loadJumpDefaultPct": None,                                                                                                                                                                                                  
                    "loadJumpMaxPct": None,                                                                                                                                                                                                      
                    "loadJumpOvercapUntil": None,                                                                                                                                                                                                
                    "muscleGroups": ["BACK_GLUTEAL"],                                                                                                                                                                                            
                    "secondaryMuscleGroups": ["BACK_HAMSTRING"]                                                                                                                                                                                  
                },                                                                                                                                                                                                                               
                {                                                                                                                                                                                                                                
                    "id": "55555555-5555-5555-5555-555555555555",                                                                                                                                                                                
                    "type": "Rest",                                                                                                                                                                                                              
                    "enabled": True,                                                                                                                                                                                                             
                    "timeInSeconds": 180                                                                                                                                                                                                         
                }                                                                                                                                                                                                                                
            ],                                                                                                                                                                                                                                   
            "order": 0,                                                                                                                                                                                                                          
            "enabled": True,                                                                                                                                                                                                                     
            "usePolarDevice": False,                                                                                                                                                                                                             
            "creationDate": "2026-01-06",                                                                                                                                                                                                        
            "previousVersionId": None,                                                                                                                                                                                                           
            "nextVersionId": None,
            "isActive": True,                                                                                                                                                                                                                    
            "timesCompletedInAWeek": None,                                                                                                                                                                                                       
            "globalId": "66666666-6666-6666-6666-666666666666",                                                                                                                                                                                  
            "type": 0                                                                                                                                                                                                                            
        }                                                                                                                                                                                                                                        
    ],                                                                                                                                                                                                                                           
    "equipments": [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "type": "BARBELL",
            "name": "Standard Barbell",
            "availablePlates": [
                {"weight": 20.0, "thickness": 30},
                {"weight": 15.0, "thickness": 25},
                {"weight": 10.0, "thickness": 20}
            ],
            "barWeight": 20.0,
            "sleeveLength": 200
        }
    ],
    "polarDeviceId": None,                                                                                                                                                                                                                       
    "birthDateYear": 1990,                                                                                                                                                                                                                       
    "weightKg": 80.0,                                                                                                                                                                                                                            
    "progressionPercentageAmount": 2.5                                                                                                                                                                                                           
}                                                                                                                                                                                                                                                   
PARALLEL_LOG_REQUEST_TRUNCATE = 8000
DEEPSEEK_CHAT_DEFAULT_TOKENS = 4000
DEEPSEEK_CHAT_MAX_TOKENS = 8000
DEEPSEEK_REASONER_DEFAULT_TOKENS = 32768
DEEPSEEK_REASONER_MAX_TOKENS = 65536

BASE_SYSTEM_PROMPT = (
    "You are a workout assistant. In normal chat mode, respond conversationally. "
    "When I later ask for JSON, you will be called with JSON output mode.\n\n"
    "IMPORTANT GUIDELINES FOR CONVERSATION:\n"
    "1. ASSESS INFORMATION COMPLETENESS FIRST — then ask only if needed:\n"
    "   - Treat the user's message as a complete workout plan when it contains:\n"
    "     * Multiple exercises with names, and\n"
    "     * Work sets × reps (e.g. 3×4–8, 2×10–15) or similar specifications, and\n"
    "     * Rest periods (e.g. 2:00, 1:30, or 'Rest (sets)' / 'Rest (to next)'), and\n"
    "     * Primary (and optionally secondary) muscle groups (e.g. FRONT_QUADRICEPS, BACK_GLUTEAL), and\n"
    "     * Form notes or cues per exercise (or at least clear exercise descriptions).\n"
    "   - Also treat as complete if the user provides structured days (e.g. 'Day A', 'Day B') or a table of exercises with sets, reps, rest, and muscle groups.\n"
    "   - When you detect a complete workout plan and the user is asking you to generate it:\n"
    "     * Do NOT ask about fitness goals, progression scheme, frequency, experience level, or constraints.\n"
    "     * Acknowledge the plan, confirm you have what you need, and call generate_workout (or say you will generate) immediately.\n"
    "   - Only ask clarifying questions when information is missing: e.g. no exercise list, no sets/reps, or the user has not asked to generate yet and the plan is vague.\n"
    "   - If the plan is incomplete, you may ask about: target muscle groups, training style (strength/hypertrophy/endurance), intensity/duration, objectives, or constraints.\n\n"
    "2. Ask about available equipment only when it is not already provided (e.g. no equipment file loaded):\n"
    "   - What equipment does the user have access to? (barbells, dumbbells, machines, bodyweight, etc.)\n"
    "   - What is their home gym or gym setup like?\n"
    "   - Note this information and remember it throughout the conversation\n\n"
    "   EQUIPMENT FILE AND CONVERSATIONAL CREATION:\n"
    "   - If an equipment file is provided, the equipment from that file is IMMUTABLE - it cannot be edited, modified, or removed\n"
    "   - However, you can still create NEW equipment or accessories through conversation if needed for the workout\n"
    "   - When generating a workout and you notice necessary equipment or accessories are missing:\n"
    "     * First check if the equipment or accessory exists in the provided file (equipments and accessoryEquipments)\n"
    "     * If missing, you MUST add it: ask the user, e.g. 'I notice you need [equipment_name] for this workout, but it's not in your equipment file. Would you like me to create it? I'll need [details]...'\n"
    "     * For main equipment: collect all required details following the equipment detail collection guide below\n"
    "     * For accessories: select the name automatically from context (e.g. exercise name, type, or common choice like 'Pull-up bar', 'Resistance Bands'); use id ACCESSORY_X and type 'ACCESSORY'; add the new entry to accessoryEquipments\n"
    "     * Create the new equipment or accessory entry with proper placeholder IDs (EQUIPMENT_X or ACCESSORY_X) that don't conflict with existing\n"
    "   - CRITICAL: Never modify, edit, or change any equipment or accessories from the provided file - they must remain exactly as provided\n"
    "   - Use provided equipment exactly as-is - do not attempt to 'improve' or modify it\n\n"
    "   CRITICAL: When a user mentions equipment, you MUST collect ALL required details before proceeding.\n"
    "   ALWAYS ask for missing information first. Only suggest defaults if the user doesn't know the values.\n"
    "   Do NOT proceed with workout generation until all equipment details are collected.\n\n"
    "   EQUIPMENT DETAIL COLLECTION GUIDE:\n\n"
    "   For BARBELL equipment, you MUST ask for:\n"
    "   - Available plates: weight (in kg) and thickness (in mm) for each plate type\n"
    "     Example question: 'What plates do you have? For each plate type, I need the weight (kg) and thickness (mm).'\n"
    "   - Bar weight: the weight of the empty barbell (in kg)\n"
    "     Example question: 'What's the weight of your barbell bar?'\n"
    "   - Bar length: the sleeve length (in mm) - the part where plates are loaded, not the total barbell length\n"
    "     Example question: 'What's the sleeve length of your barbell bar (the part where plates are loaded)?'\n"
    "   - If user doesn't know: Suggest defaults - Standard bar: 20kg weight, 406mm sleeve length.\n"
    "     Common plates: 20kg/30mm, 15kg/25mm, 10kg/20mm, 5kg/15mm, 2.5kg/10mm, 1.25kg/5mm\n"
    "     Always ask: 'Would you like me to use these standard values?'\n\n"
    "   For DUMBBELLS (pair) or DUMBBELL (single) equipment, you MUST ask for:\n"
    "   - Available dumbbell weights: list all dumbbell weights available (in kg)\n"
    "     Example question: 'What dumbbell weights do you have? Please list all available weights in kg.'\n"
    "   - Extra weights: any additional weights that can be added to dumbbells (in kg)\n"
    "     Example question: 'Do you have any extra weights that can be added to your dumbbells? If so, what weights?'\n"
    "   - Max extra weights per loading point: how many extra weights can be added per side\n"
    "     Example question: 'How many extra weights can you add to each side of a dumbbell?'\n"
    "   - If user doesn't know: Suggest defaults - Common dumbbell set: 5kg, 10kg, 15kg, 20kg, 25kg.\n"
    "     If no extra weights mentioned: maxExtraWeightsPerLoadingPoint = 0, extraWeights = []\n"
    "     Always ask: 'Would you like me to use these standard values?'\n\n"
    "   For PLATELOADEDCABLE equipment, you MUST ask for:\n"
    "   - Available plates: weight (in kg) and thickness (in mm) for each plate type\n"
    "     Example question: 'What plates does your cable machine use? For each plate type, I need the weight (kg) and thickness (mm).'\n"
    "   - Bar length: the sleeve length (in mm) - the part where plates are loaded\n"
    "     Example question: 'What's the sleeve length of your cable machine bar attachment (the part where plates are loaded)?'\n"
    "   - If user doesn't know: Suggest defaults - Similar to barbell plates: 20kg/30mm, 15kg/25mm, 10kg/20mm, 5kg/15mm, 2.5kg/10mm.\n"
    "     Bar length: 406mm (standard). Always ask: 'Would you like me to use these standard values?'\n\n"
    "   For WEIGHTVEST equipment, you MUST ask for:\n"
    "   - Available weight increments: list all weight options available for the vest (in kg)\n"
    "     Example question: 'What weight increments does your weight vest support? Please list all available weights in kg.'\n"
    "   - If user doesn't know: Suggest defaults - Common increments: 5kg, 10kg, 15kg, 20kg, 25kg.\n"
    "     Always ask: 'Would you like me to use these standard values?'\n\n"
    "   For MACHINE equipment, you MUST ask for:\n"
    "   - Available weight stack weights: list all weights in the machine's weight stack (in kg)\n"
    "     Example question: 'What weights are available on your machine? Please list all weight stack options in kg.'\n"
    "   - Extra weights: any additional weights that can be added to the machine (in kg)\n"
    "     Example question: 'Can you add extra weights to your machine? If so, what weights are available?'\n"
    "   - Max extra weights per loading point: how many extra weights can be added\n"
    "     Example question: 'How many extra weights can you add to the machine?'\n"
    "   - If user doesn't know: Suggest defaults - Common weight stack: 5kg increments from 5kg to 100kg.\n"
    "     If no extra weights mentioned: maxExtraWeightsPerLoadingPoint = 0, extraWeights = []\n"
    "     Always ask: 'Would you like me to use these standard values?'\n\n"
    "   For ACCESSORY equipment (e.g. resistance bands, pull-up bar, suspension trainer):\n"
    "   - Select the name automatically from context: infer from the exercise (e.g. pull-ups → 'Pull-up bar', band work → 'Resistance Bands', TRX → 'Suspension trainer') or use a sensible default. Use id ACCESSORY_X and type 'ACCESSORY'. Do not ask the user for the name.\n\n"
    "   IMPORTANT REMINDERS:\n"
    "   - NEVER assume equipment details - always ask explicitly\n"
    "   - If a user mentions equipment but doesn't provide all details, ask follow-up questions immediately\n"
    "   - When suggesting defaults, always phrase it as a question: 'Would you like me to use [default values]?'\n"
    "   - Do NOT proceed to workout generation if equipment details are incomplete\n"
    "   - Remember all equipment details throughout the conversation for later workout generation\n\n"
    "3. Exercise recommendations:\n"
    "   - ONLY suggest exercises that can be performed with the equipment the user has available\n"
    "   - If the user mentions equipment later, update your recommendations accordingly\n"
    "   - If an exercise requires equipment they don't have, suggest alternatives that use their available equipment\n"
    "   - Recognize when users want unilateral exercises (single-arm or single-leg movements)\n"
    "     * These exercises help with muscle imbalances and unilateral strength development\n"
    "     * Examples: single-arm rows, single-leg squats, Bulgarian split squats\n"
    "     * When generating workouts, mark these exercises as unilateral (see JSON generation instructions)\n\n"
    "4. Workout preview format:\n"
    "   - When suggesting a workout during conversation (before JSON generation), present it in a plain text table format\n"
    "   - Use the following column structure: Exercise Name | Sets | Reps/Time | Weight/Notes | Rest\n"
    "   - Formatting guidelines for visual clarity:\n"
    "     * Use '=' characters for top and bottom borders (minimum 60 characters wide)\n"
    "     * Use '-' characters for header separator line (same width as borders)\n"
    "     * Ensure consistent spacing: at least 1 space before and after each pipe (|)\n"
    "     * Column width guidelines: Exercise Name (20+ chars), Sets (6+ chars), Reps/Time (12+ chars), Weight/Notes (15+ chars), Rest (8+ chars)\n"
    "     * Alignment rules:\n"
    "       - Exercise Name: left-aligned\n"
    "       - Sets: center-aligned\n"
    "       - Reps/Time: center-aligned\n"
    "       - Weight/Notes: center-aligned\n"
    "       - Rest: right-aligned\n"
    "     * Use consistent padding for numeric values (e.g., '  3  ' for sets, '  5  ' for reps)\n"
    "   - Example format with proper visual clarity:\n"
    "     ============================================================\n"
    "     Exercise Name         | Sets | Reps/Time | Weight/Notes | Rest\n"
    "     ------------------------------------------------------------\n"
    "     Back Squat            |  3   |    5      |    100kg     | 120s\n"
    "     Bench Press           |  3   |    8      |     80kg     |  90s\n"
    "     Overhead Press        |  3   |    6      |     60kg     |  90s\n"
    "     ============================================================\n"
    "   - Keep tables readable and well-formatted with consistent spacing and alignment\n\n"
    "5. Maintain a friendly, conversational tone while being structured and helpful.\n\n"
    "6. When suggesting workouts or exercises in conversation, keep any written notes or descriptions brief and to the point.\n"
    "   - Prefer short phrases or one short sentence instead of long paragraphs.\n"
    "   - Focus on essential cues (tempo, form reminders, special constraints) only.\n\n"
    "7. Function calling for workout generation:\n"
    "   - You have access to a 'generate_workout' function tool that generates workout JSON files\n"
    "   - Use this function when the user explicitly asks you to generate a workout or create workout JSON\n"
    "   - The function will use the entire conversation context to generate the workout\n"
    "   - You can optionally provide a 'custom_prompt' parameter with additional instructions\n"
    "   - After calling this function, the conversation will end and the program will exit\n"
    "   - Do NOT call this function unless the user explicitly requests workout generation"
)

SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context condenser for workout generation. Your task is to extract and condense only the essential "
    "information needed to generate a workout from a conversation history, discarding all irrelevant conversation.\n\n"
    "Extract and condense ONLY the following information:\n"
    "1. User's fitness goals and objectives (e.g., strength training, hypertrophy, endurance, weight loss)\n"
    "2. Target muscle groups or areas (e.g., chest, legs, full body)\n"
    "3. Training style preferences (e.g., powerlifting, bodybuilding, circuit training)\n"
    "4. Available equipment mentioned (list all equipment with any details provided)\n"
    "5. Workout intensity preferences (e.g., high intensity, moderate, beginner-friendly)\n"
    "6. Workout duration preferences (e.g., 30 minutes, 60 minutes, quick sessions)\n"
    "7. Specific constraints or requirements (e.g., no running, knee-friendly, home gym only)\n"
    "8. Any specific exercises or workout types the user wants included or excluded\n\n"
    "IMPORTANT:\n"
    "- Ignore conversational fluff, greetings, and repeated information\n"
    "- Focus on actionable information that affects workout generation\n"
    "- Be concise but complete - include all relevant details\n"
    "- Format as a clear, structured condensation that can be used directly for generation\n"
    "- If information is missing or unclear, note it but don't make assumptions\n"
)

JSON_SYSTEM_PROMPT = (
    "You must output JSON only. The output must be valid json. "
    "Do not include markdown or extra text. "
    "Use valid UUIDs and ISO dates (YYYY-MM-DD). "
    "Use equipmentId values that exist in equipments. "
    "Use RestSet between sets and Rest component between exercises when appropriate. "
    "Do NOT use IRONNECK equipment.\n\n"
    "REST PERIODS - CRITICAL DISTINCTION:\n"
    "There are TWO different types of rest periods in the workout structure:\n\n"
    "1. RestSet (for rest BETWEEN SETS within an exercise):\n"
    "   - Location: Inside the 'sets' array of an Exercise object\n"
    "   - Structure: {type: \"RestSet\", id: UUID, timeInSeconds: integer, subCategory: \"WorkSet\"}\n"
    "   - Purpose: Rest period between consecutive sets of the SAME exercise\n"
    "   - Example: Squat Set 1 → RestSet (90s) → Squat Set 2 → RestSet (90s) → Squat Set 3\n"
    "   - Typical duration: 30-300 seconds (60-120s for strength, 30-60s for hypertrophy)\n"
    "   - Placement: Insert RestSet objects between work sets in the exercise's sets array\n\n"
    "2. Rest Component (for rest BETWEEN DIFFERENT EXERCISES):\n"
    "   - Location: In the 'workoutComponents' array at the workout level\n"
    "   - Structure: {type: \"Rest\", id: UUID, enabled: boolean, timeInSeconds: integer}\n"
    "   - Purpose: Rest period between different exercises in the workout sequence\n"
    "   - Example: Exercise A → Rest Component (180s) → Exercise B → Rest Component (180s) → Exercise C\n"
    "   - Placement: Insert Rest components between Exercise components in workoutComponents array\n\n"
    "   REST DURATION DECISION RULES (CRITICAL - Apply consistently):\n"
    "   Determine rest timeInSeconds based on the PREVIOUS exercise (the one just completed):\n\n"
    "   A. Training Goal-Based Defaults:\n"
    "      - Strength training (1-5 reps, 85-100% load): 180 seconds (3 minutes)\n"
    "      - Hypertrophy training (6-12 reps, 65-85% load): 120 seconds (2 minutes)\n"
    "      - Endurance training (12+ reps, 50-70% load): 90 seconds (1.5 minutes)\n\n"
    "   B. Exercise Type Adjustments:\n"
    "      - Compound movements (squats, deadlifts, bench press, rows, overhead press):\n"
    "        * Add 30-60 seconds to the base duration\n"
    "        * Strength compound: 180-240s, Hypertrophy compound: 120-180s, Endurance compound: 90-120s\n"
    "      - Isolation movements (curls, tricep extensions, lateral raises, leg curls):\n"
    "        * Use base duration or subtract 30 seconds\n"
    "        * Strength isolation: 120-180s, Hypertrophy isolation: 90-120s, Endurance isolation: 60-90s\n\n"
    "   C. Muscle Group Overlap Adjustments:\n"
    "      - If next exercise targets SAME primary muscle group: Add 30-60 seconds\n"
    "      - If next exercise targets DIFFERENT muscle groups: Use base duration\n"
    "      - If next exercise is antagonist pair (e.g., biceps after triceps): Subtract 30 seconds\n\n"
    "   D. Final Duration Guidelines:\n"
    "      - Minimum: 60 seconds (only for low-intensity isolation exercises)\n"
    "      - Maximum: 240 seconds (only for very heavy compound strength exercises)\n"
    "      - Most common: 120-180 seconds (hypertrophy/strength compound movements)\n"
    "      - Keep rest periods CONSISTENT within the same workout unless there's a clear reason to vary\n"
    "      - If unsure, use 120 seconds as a safe default for most exercises\n\n"
    "   E. Consistency Rules:\n"
    "      - Use the SAME rest duration for similar exercise types in the same workout\n"
    "      - Only vary rest if exercises clearly differ in intensity or muscle group overlap\n"
    "      - Example: All compound strength exercises → 180s, all isolation hypertrophy → 120s\n\n"
    "IMPORTANT RULES:\n"
    "   - NEVER use RestSet in workoutComponents array (RestSet only belongs in exercise.sets)\n"
    "   - NEVER use Rest Component inside an exercise's sets array (Rest Component only belongs in workoutComponents)\n"
    "   - RestSet = rest within one exercise (between its sets)\n"
    "   - Rest Component = rest between different exercises\n\n"
    "NOTES AND DESCRIPTIONS:\n"
    "- Keep all free-text fields such as workout 'description' and exercise 'notes' brief and concise.\n"
    "- Workout 'description' field has a MAXIMUM of 50 characters - keep it short and focused.\n"
    "- Exercise 'notes' field has a MAXIMUM of 500 characters - keep it brief and focused on essential cues only.\n"
    "- Prefer short phrases or a single short sentence (e.g., \"Focus on depth and bracing\") instead of long paragraphs.\n"
    "- Avoid verbose explanations or multi-sentence coaching in these fields.\n\n"
    "WORKOUT ORDERING:\n"
    "- workout.order is a 0-based integer used to sort workouts in the app\n"
    "- Set order sequentially (0, 1, 2...) matching the workouts array order\n"
    "- For a single workout, use order = 0\n"
    "- Keep order values unique unless user explicitly requests otherwise\n\n"
    "EXERCISE HISTORY (doNotStoreHistory):\n"
    "- Set doNotStoreHistory = true only for warmup-only, cooldown/mobility, technique drills, tests, or when user asks not to log\n"
    "- Otherwise set doNotStoreHistory = false for standard working sets\n"
    "- If doNotStoreHistory = true, keep enableProgression = false; still populate reps, load percents, and sets correctly\n\n"
    "ADVANCED OPTIONAL FIELDS (ONLY WHEN EXPLICITLY REQUESTED):\n"
    "- Heart-rate target zone:\n"
    "  * Use lowerBoundMaxHRPercent and upperBoundMaxHRPercent ONLY if the user explicitly asks for HR targets/zones\n"
    "  * Otherwise set both fields to null\n"
    "  * If set, both must be present and between 1 and 100 (lower < upper)\n"
    "  * Use standard zones unless a custom zone is requested:\n"
    "    - Zone 2: 60-70%, Zone 3: 70-80%, Zone 4: 80-90%, Zone 5: 90-100%\n"
    "- Load jump settings for progression:\n"
    "  * Use loadJumpDefaultPct, loadJumpMaxPct, loadJumpOvercapUntil ONLY if the user explicitly asks to tune progression jumps\n"
    "  * Otherwise set all three fields to null (app defaults will be used)\n"
    "  * If set: loadJumpDefaultPct ~ 0.025 (2.5%), loadJumpMaxPct ~ 0.10 (10%, must be >= default and <= 0.25),\n"
    "    loadJumpOvercapUntil ~ 2 (0-5 allowed)\n\n"
    "VALIDATION CHECKLIST - Verify all exercises meet these requirements:\n\n"
    "1. Exercise Type Consistency:\n"
    "   - WEIGHT exercises contain only WeightSet (plus RestSet between sets)\n"
    "   - BODY_WEIGHT exercises contain only BodyWeightSet (plus RestSet between sets)\n"
    "   - COUNTUP exercises contain only EnduranceSet (plus RestSet between sets)\n"
    "   - COUNTDOWN exercises contain only TimedDurationSet (plus RestSet between sets)\n\n"
    "2. Reps Range:\n"
    "   - COUNTUP/COUNTDOWN: minReps=0 AND maxReps=0\n"
    "   - WEIGHT/BODY_WEIGHT: minReps > 0 AND maxReps > 0 AND minReps <= maxReps\n\n"
    "3. Load Percent Range (CRITICAL for double progression):\n"
    "   - WEIGHT/BODY_WEIGHT: minLoadPercent > 0 AND maxLoadPercent > 0 AND minLoadPercent < maxLoadPercent\n"
    "     * Typical ranges: 50-100% (strength: 85-100%, hypertrophy: 65-85%, endurance: 50-70%)\n"
    "     * If enableProgression=true, these MUST be set correctly - they define the intensity range for progression\n"
    "   - COUNTUP/COUNTDOWN: Can be 0.0 (not applicable)\n\n"
    "4. Muscle Groups:\n"
    "   - Every exercise has at least one muscle group in muscleGroups array\n"
    "   - All muscle group values are valid enum values (check against schema)\n\n"
    "5. Equipment References:\n"
    "   - All equipmentId values (if not null) reference valid equipment IDs in the equipments array\n\n"
    "6. Unilateral Exercises (intraSetRestInSeconds):\n"
    "   - Set intraSetRestInSeconds to a positive integer (> 0) for exercises performed on one side at a time\n"
    "   - The app will automatically duplicate sets for left/right sides with rest between them\n"
    "   - Common for single-arm/single-leg movements (e.g., single-arm rows, single-leg squats, Bulgarian split squats)\n"
    "   - Set to null or 0 for bilateral exercises (default for most exercises)\n"
    "   - Typical values: 30-60s for isolation, 60-120s for compound unilateral movements\n\n"
    "7. Set Type Field Requirements:\n"
    "   - TimedDurationSet: Must have timeInMillis (integer, milliseconds), autoStart (boolean), autoStop (boolean). NO subCategory.\n"
    "   - EnduranceSet: Must have timeInMillis (integer, milliseconds), autoStart (boolean), autoStop (boolean). NO subCategory.\n"
    "   - WeightSet: Must have reps (integer), weight (number), subCategory (string)\n"
    "   - BodyWeightSet: Must have reps (integer), additionalWeight (number), subCategory (string)\n"
    "   - RestSet: Must have timeInSeconds (integer), subCategory=\"WorkSet\" (standard case)\n\n"
    "8. RestSet Configuration (REST BETWEEN SETS WITHIN AN EXERCISE):\n"
    "   - RestSet is ONLY used inside the 'sets' array of an Exercise object\n"
    "   - RestSet represents rest periods BETWEEN consecutive sets of the SAME exercise\n"
    "   - All RestSet objects have subCategory=\"WorkSet\" (standard case)\n"
    "   - RestSet timeInSeconds is reasonable (30-300 seconds typically):\n"
    "     * Strength: 60-180s, Hypertrophy: 30-90s, Endurance: 30-60s\n"
    "   - Example: [WeightSet, RestSet(90s), WeightSet, RestSet(90s), WeightSet]\n"
    "   - DO NOT use RestSet for rest between different exercises\n\n"
    "JSON Schema:\n"
    f"{json.dumps(JSON_SCHEMA, indent=2)}\n\n"
    "Example JSON Output:\n"
    f"{json.dumps(EXAMPLE_JSON, indent=2)}"
)

SELF_HEAL_SYSTEM_PROMPT = (
    "You are a JSON schema validation error fixer. Your task is to fix validation errors in workout JSON data.\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. Analyze the validation error message carefully to understand what field(s) are invalid\n"
    "2. Identify the exact JSON path where the error occurs (e.g., workouts[0].workoutComponents[3].muscleGroups)\n"
    "3. Understand the schema requirement from the error message (e.g., 'minItems: 1' means array must have at least 1 item)\n"
    "4. Fix ONLY the problematic field(s) - do NOT modify any other valid data\n"
    "5. Preserve all UUIDs, IDs, and relationships between objects\n"
    "6. Maintain the structure and intent of the original workout\n"
    "7. Use valid enum values from the schema when applicable\n\n"
    "INPUT FORMAT:\n"
    "You may receive EITHER:\n"
    "- A complete WorkoutStore JSON structure (full healing mode)\n"
    "- A partial JSON structure with an 'item' field containing only the failing item (targeted healing mode)\n"
    "  * In targeted mode, the input will have: {item: {...}, itemType: '...', context: {...}}\n"
    "  * The 'context' field provides minimal context needed (e.g., equipments list for validation)\n\n"
    "OUTPUT FORMAT:\n"
    "- If you receive a complete WorkoutStore structure: Return the complete corrected JSON structure\n"
    "- If you receive a partial structure with 'item' field: Return ONLY the fixed item (the corrected value of 'item'), not the wrapper\n"
    "  * Example: If input is {item: {name: 'Squat', muscleGroups: []}, ...}, return {name: 'Squat', muscleGroups: ['FRONT_QUADRICEPS', 'BACK_GLUTEAL'], ...}\n"
    "  * Do NOT return {item: {...}} - return just the item itself\n\n"
    "CONTEXT-AWARE FIXING (CRITICAL):\n"
    "When fixing errors, you must set values that make SENSE in the context of the workout, not just values that pass schema validation.\n"
    "- For empty arrays: Populate with contextually appropriate values based on the exercise/workout name, equipment used, and related fields\n"
    "- For missing required fields: Add values that are appropriate for the specific exercise/workout type and context\n"
    "- For invalid enum values: Replace with the most contextually appropriate valid enum value\n"
    "- For type mismatches: Convert to the correct type while preserving the semantic meaning\n"
    "- For constraint violations: Adjust values to meet requirements while maintaining logical consistency\n"
    "- Use secondary fields (like secondaryMuscleGroups, exercise name, equipment type) as hints for appropriate values\n"
    "- Consider the exercise type (WEIGHT, BODY_WEIGHT, COUNTUP, COUNTDOWN) when determining appropriate values\n"
    "- Use the 'context' field when provided (e.g., check equipmentId against context.equipments list)\n\n"
    "EXAMPLES OF CONTEXT-AWARE FIXING:\n"
    "- Empty muscleGroups: Infer from exercise name (e.g., 'Squat' -> ['FRONT_QUADRICEPS', 'BACK_GLUTEAL']), or use secondaryMuscleGroups if available. When inferring for compound exercises, add 2-3 primary movers (e.g. Squat -> FRONT_QUADRICEPS, BACK_GLUTEAL; Bench -> FRONT_CHEST, FRONT_DELTOIDS, FRONT_TRICEPS) and populate secondaryMuscleGroups with 1-2 synergists when relevant.\n"
    "- Invalid muscleGroups enum values: Replace invalid values with valid enum values from the schema. Common fixes:\n"
    "  * 'CHEST' → 'FRONT_CHEST', 'QUADS'/'QUADRICEPS' → 'FRONT_QUADRICEPS'\n"
    "  * 'HAMSTRINGS' → 'BACK_HAMSTRING', 'GLUTES'/'GLUTEAL' → 'BACK_GLUTEAL'\n"
    "  * 'BICEPS' → 'FRONT_BICEPS', 'TRICEPS' → 'FRONT_TRICEPS' or 'BACK_TRICEPS' (context-dependent)\n"
    "  * 'SHOULDERS'/'DELTS' → 'FRONT_DELTOIDS' or 'BACK_DELTOIDS', 'ABS' → 'FRONT_ABS'\n"
    "  * 'LATS'/'LATISSIMUS' → 'BACK_UPPER_BACK', 'TRAPS' → 'FRONT_TRAPEZIUS' or 'BACK_TRAPEZIUS'\n"
    "  * Use exercise name and context to determine correct FRONT vs BACK prefix when ambiguous\n"
    "  * Valid enum values: FRONT_ABS, FRONT_ADDUCTORS, FRONT_ANKLES, FRONT_BICEPS, FRONT_CALVES, FRONT_CHEST, FRONT_DELTOIDS, FRONT_FEET, FRONT_FOREARM, FRONT_HANDS, FRONT_KNEES, FRONT_NECK, FRONT_OBLIQUES, FRONT_QUADRICEPS, FRONT_TIBIALIS, FRONT_TRAPEZIUS, FRONT_TRICEPS, BACK_ADDUCTORS, BACK_ANKLES, BACK_CALVES, BACK_DELTOIDS, BACK_FEET, BACK_FOREARM, BACK_GLUTEAL, BACK_HAMSTRING, BACK_HANDS, BACK_LOWER_BACK, BACK_NECK, BACK_TRAPEZIUS, BACK_TRICEPS, BACK_UPPER_BACK\n"
    "- Missing equipmentId: Set to null if it's a bodyweight exercise, or match to appropriate equipment from context.equipments array\n"
    "- Missing exerciseCategory (for WEIGHT/BODY_WEIGHT): Infer from exercise name: HEAVY_COMPOUND (squat, deadlift, bench, OHP, rows), MODERATE_COMPOUND (lunges, split squats, hip thrusts, pull-ups, machine presses), ISOLATION (curls, lateral raises, triceps, calf raises)\n"
    "- Invalid exerciseType: Choose based on the sets array content (WeightSet → WEIGHT, BodyWeightSet → BODY_WEIGHT, etc.)\n"
    "- Constraint violation on loadPercent: Adjust to reasonable range for the exercise type and rep range\n"
    "- Optional advanced fields: Only fix these if they already exist in the item\n"
    "  * lowerBoundMaxHRPercent and upperBoundMaxHRPercent must be set together (both null or both numbers)\n"
    "  * If set, clamp to 1-100 with lower < upper; otherwise set both to null\n"
    "  * loadJumpDefaultPct, loadJumpMaxPct, loadJumpOvercapUntil should only be adjusted if present\n"
    "  * If present, keep loadJumpDefaultPct in [0.0, 0.10], loadJumpMaxPct in [defaultPct, 0.25], loadJumpOvercapUntil in [0, 5]\n"
    "- Invalid weight combinations: For WEIGHT exercises with equipment, WeightSet weights MUST match valid equipment combinations. "
    "For BODY_WEIGHT exercises with equipment, BodyWeightSet additionalWeight MUST match valid equipment combinations. "
    "Calculate valid combinations from equipment's available plates/weights and fix to the nearest valid weight. "
    "If context includes equipment weight combinations, use those values. Otherwise, calculate from equipment structure:\n"
    "  * BARBELL: Sum of plates (both sides) + barWeight, considering sleeveLength constraint\n"
    "  * DUMBBELLS/DUMBBELL: Available dumbbell weights × loading points + extra weight combinations\n"
    "  * MACHINE: Available weights + extra weight combinations\n"
    "  * PLATELOADEDCABLE: Sum of plates, considering sleeveLength constraint\n"
    "  * WEIGHTVEST: Available weight values\n"
    "OUTPUT REQUIREMENTS:\n"
    "You must output JSON only. The output must be valid JSON.\n"
    "Do not include markdown, explanations, or extra text - only the corrected JSON.\n"
    "In targeted mode, return only the fixed item, not a wrapper structure.\n"
)

# Simplified equipment schema for incremental generation
EQUIPMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "equipments": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"$ref": "#/$defs/EquipmentBarbell"},
                    {"$ref": "#/$defs/EquipmentDumbbells"},
                    {"$ref": "#/$defs/EquipmentDumbbell"},
                    {"$ref": "#/$defs/EquipmentPlateLoadedCable"},
                    {"$ref": "#/$defs/EquipmentWeightVest"},
                    {"$ref": "#/$defs/EquipmentMachine"}
                ]
            }
        }
    },
    "$defs": JSON_SCHEMA["$defs"]
}

EQUIPMENT_EXAMPLE = {
    "equipments": [
        {
            "id": "EQUIPMENT_0",
            "type": "BARBELL",
            "name": "Standard Barbell",
            "availablePlates": [
                {"weight": 20.0, "thickness": 30.0},
                {"weight": 15.0, "thickness": 25.0},
                {"weight": 10.0, "thickness": 20.0}
            ],
            "barWeight": 20.0,
            "sleeveLength": 406
        },
        {
            "id": "EQUIPMENT_1",
            "type": "DUMBBELLS",
            "name": "Standard Dumbbells",
            "maxExtraWeightsPerLoadingPoint": 0,
            "extraWeights": [],
            "dumbbells": [
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0}
            ]
        },
        {
            "id": "EQUIPMENT_2",
            "type": "DUMBBELL",
            "name": "Single Dumbbell",
            "maxExtraWeightsPerLoadingPoint": 0,
            "extraWeights": [],
            "dumbbells": [
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0}
            ]
        },
        {
            "id": "EQUIPMENT_3",
            "type": "PLATELOADEDCABLE",
            "name": "Cable Machine",
            "availablePlates": [
                {"weight": 10.0, "thickness": 20.0},
                {"weight": 5.0, "thickness": 15.0},
                {"weight": 2.5, "thickness": 10.0}
            ],
            "sleeveLength": 300
        },
        {
            "id": "EQUIPMENT_4",
            "type": "WEIGHTVEST",
            "name": "Weight Vest",
            "availableWeights": [
                {"weight": 5.0},
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0}
            ]
        },
        {
            "id": "EQUIPMENT_5",
            "type": "MACHINE",
            "name": "Weight Machine",
            "availableWeights": [
                {"weight": 5.0},
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0},
                {"weight": 25.0}
            ],
            "maxExtraWeightsPerLoadingPoint": 2,
            "extraWeights": [
                {"weight": 2.5},
                {"weight": 5.0}
            ]
        },
        {
            "id": "EQUIPMENT_6",
            "type": "ACCESSORY",
            "name": "Resistance Bands"
        }
    ]
}

EQUIPMENT_SYSTEM_PROMPT = (
    "You must output JSON only. The output must be valid json. "
    "Do not include markdown or extra text.\n\n"
    "Generate ONLY the equipment list. Use placeholder IDs in the format EQUIPMENT_0, EQUIPMENT_1, EQUIPMENT_2, etc.\n"
    "Do NOT use real UUIDs - use placeholder IDs only.\n"
    "Do NOT use IRONNECK equipment.\n\n"
    "VALID EQUIPMENT TYPES (use EXACTLY these strings, case-sensitive):\n"
    "- BARBELL: Barbell with plates - requires: id, type, name, availablePlates (array of objects with {weight: number, thickness: number in mm}), barWeight, sleeveLength (in mm)\n"
    "  * CRITICAL: availablePlates must be an array of objects with both weight and thickness. Example: [{\"weight\": 20.0, \"thickness\": 20.0}, {\"weight\": 15.0, \"thickness\": 20.0}] NOT [20.0, 15.0]\n"
    "- DUMBBELLS: Pair of dumbbells - requires: id, type, name, maxExtraWeightsPerLoadingPoint, extraWeights (array of objects with {weight: number}), dumbbells (array of objects with {weight: number})\n"
    "  * CRITICAL: extraWeights and dumbbells must be arrays of objects, NOT numbers. Example: [{\"weight\": 5.0}, {\"weight\": 10.0}] NOT [5.0, 10.0]\n"
    "- DUMBBELL: Single dumbbell - requires: id, type, name, maxExtraWeightsPerLoadingPoint, extraWeights (array of objects with {weight: number}), dumbbells (array of objects with {weight: number})\n"
    "  * CRITICAL: extraWeights and dumbbells must be arrays of objects, NOT numbers. Example: [{\"weight\": 5.0}, {\"weight\": 10.0}] NOT [5.0, 10.0]\n"
    "- PLATELOADEDCABLE: Cable machine - requires: id, type, name, availablePlates (array of objects with {weight: number, thickness: number in mm}), sleeveLength (in mm)\n"
    "  * CRITICAL: availablePlates must be an array of objects with both weight and thickness. Example: [{\"weight\": 20.0, \"thickness\": 20.0}, {\"weight\": 15.0, \"thickness\": 20.0}] NOT [20.0, 15.0]\n"
    "- WEIGHTVEST: Weighted vest - requires: id, type, name, availableWeights (array of objects with {weight: number}) - NOTE: type is 'WEIGHTVEST' not 'WEIGHTED_VEST'\n"
    "  * CRITICAL: availableWeights must be an array of objects, NOT numbers. Example: [{\"weight\": 1.0}, {\"weight\": 2.0}] NOT [1.0, 2.0]\n"
    "- MACHINE: Weight machine - requires: id, type, name, availableWeights (array of objects with {weight: number}), maxExtraWeightsPerLoadingPoint, extraWeights (array of objects with {weight: number})\n"
    "  * CRITICAL: availableWeights and extraWeights must be arrays of objects, NOT numbers. Example: [{\"weight\": 5.0}, {\"weight\": 10.0}] NOT [5.0, 10.0]\n"
    "- ACCESSORY: Accessory equipment (e.g., resistance bands, suspension trainer, pull-up bar) - requires: id, type, name (simpler than weight-loaded equipment - no weight specifications)\n\n"
    "Output format:\n"
    f"{json.dumps(EQUIPMENT_EXAMPLE, indent=2)}\n\n"
    "Generate all equipment needed for the workout based on the conversation."
)

# Simplified exercise schema for incremental generation
EXERCISE_SCHEMA = {
    "type": "object",
    "properties": {
        "exercises": {
            "type": "array",
            "items": {"$ref": "#/$defs/Exercise"}
        }
    },
    "$defs": JSON_SCHEMA["$defs"]
}

EXERCISE_EXAMPLE = {
    "exercises": [
        {
            "id": "EXERCISE_WARMUP",
            "type": "Exercise",
            "enabled": True,
            "name": "Warm Up",
            "doNotStoreHistory": True,
            "notes": "",
            "sets": [
                {
                    "id": "SET_WARMUP",
                    "type": "TimedDurationSet",
                    "timeInMillis": 300000,
                    "autoStart": True,
                    "autoStop": True
                }
            ],
            "exerciseType": "COUNTDOWN",
            "minLoadPercent": 0.0,
            "maxLoadPercent": 0.0,
            "minReps": 0,
            "maxReps": 0,
            "equipmentId": None,
            "bodyWeightPercentage": None,
            "generateWarmUpSets": False,
            "enableProgression": False,
            "keepScreenOn": False,
            "showCountDownTimer": True,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_QUADRICEPS"],
            "secondaryMuscleGroups": [],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": None
        },
        {
            "id": "EXERCISE_0",
            "type": "Exercise",
            "enabled": True,
            "name": "Back Squat",
            "doNotStoreHistory": False,
            "notes": "",
            "sets": [
                {
                    "id": "SET_0",
                    "type": "WeightSet",
                    "reps": 5,
                    "weight": 100.0,
                    "subCategory": "WorkSet"
                },
                {
                    "id": "SET_1",
                    "type": "RestSet",
                    "timeInSeconds": 120,
                    "subCategory": "WorkSet"
                }
            ],
            "exerciseType": "WEIGHT",
            "minLoadPercent": 85.0,
            "maxLoadPercent": 100.0,
            "minReps": 5,
            "maxReps": 5,
            "equipmentId": "EQUIPMENT_0",
            "bodyWeightPercentage": None,
            "generateWarmUpSets": False,
            "enableProgression": False,
            "keepScreenOn": False,
            "showCountDownTimer": False,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_QUADRICEPS", "BACK_GLUTEAL"],
            "secondaryMuscleGroups": ["BACK_HAMSTRING"],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": "HEAVY_COMPOUND"
        },
        {
            "id": "EXERCISE_1",
            "type": "Exercise",
            "enabled": True,
            "name": "Single-Arm Dumbbell Row",
            "doNotStoreHistory": False,
            "notes": "Focus on controlled movement",
            "sets": [
                {
                    "id": "SET_2",
                    "type": "WeightSet",
                    "reps": 8,
                    "weight": 20.0,
                    "subCategory": "WorkSet"
                },
                {
                    "id": "SET_3",
                    "type": "RestSet",
                    "timeInSeconds": 90,
                    "subCategory": "WorkSet"
                }
            ],
            "exerciseType": "WEIGHT",
            "minLoadPercent": 65.0,
            "maxLoadPercent": 85.0,
            "minReps": 8,
            "maxReps": 12,
            "equipmentId": "EQUIPMENT_1",
            "bodyWeightPercentage": None,
            "generateWarmUpSets": False,
            "enableProgression": True,
            "keepScreenOn": False,
            "showCountDownTimer": False,
            "intraSetRestInSeconds": 60,
            "muscleGroups": ["BACK_UPPER_BACK", "BACK_DELTOIDS"],
            "secondaryMuscleGroups": ["FRONT_BICEPS"],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": "MODERATE_COMPOUND"
        },
        {
            "id": "EXERCISE_2",
            "type": "Exercise",
            "enabled": True,
            "name": "Push-ups",
            "doNotStoreHistory": False,
            "notes": "Keep core tight, full range of motion",
            "sets": [
                {
                    "id": "SET_4",
                    "type": "BodyWeightSet",
                    "reps": 12,
                    "additionalWeight": 0.0,
                    "subCategory": "WorkSet"
                },
                {
                    "id": "SET_5",
                    "type": "RestSet",
                    "timeInSeconds": 60,
                    "subCategory": "WorkSet"
                },
                {
                    "id": "SET_6",
                    "type": "BodyWeightSet",
                    "reps": 12,
                    "additionalWeight": 0.0,
                    "subCategory": "WorkSet"
                }
            ],
            "exerciseType": "BODY_WEIGHT",
            "minLoadPercent": 70.0,
            "maxLoadPercent": 100.0,
            "minReps": 8,
            "maxReps": 15,
            "equipmentId": None,
            "bodyWeightPercentage": 100.0,
            "generateWarmUpSets": False,
            "enableProgression": True,
            "keepScreenOn": False,
            "showCountDownTimer": False,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["FRONT_CHEST", "FRONT_TRICEPS", "FRONT_DELTOIDS"],
            "secondaryMuscleGroups": ["FRONT_ABS"],
            "requiredAccessoryEquipmentIds": [],
            "requiresLoadCalibration": False,
            "exerciseCategory": "MODERATE_COMPOUND"
        },
        {
            "id": "EXERCISE_3",
            "type": "Exercise",
            "enabled": True,
            "name": "Pull-Ups",
            "doNotStoreHistory": False,
            "notes": "Full range of motion, controlled descent",
            "sets": [
                {
                    "id": "SET_7",
                    "type": "BodyWeightSet",
                    "reps": 8,
                    "additionalWeight": 0.0,
                    "subCategory": "WorkSet"
                },
                {
                    "id": "SET_8",
                    "type": "RestSet",
                    "timeInSeconds": 120,
                    "subCategory": "WorkSet"
                },
                {
                    "id": "SET_9",
                    "type": "BodyWeightSet",
                    "reps": 8,
                    "additionalWeight": 0.0,
                    "subCategory": "WorkSet"
                }
            ],
            "exerciseType": "BODY_WEIGHT",
            "minLoadPercent": 85.0,
            "maxLoadPercent": 100.0,
            "minReps": 5,
            "maxReps": 10,
            "equipmentId": None,
            "bodyWeightPercentage": 100.0,
            "generateWarmUpSets": False,
            "enableProgression": True,
            "keepScreenOn": False,
            "showCountDownTimer": False,
            "intraSetRestInSeconds": None,
            "muscleGroups": ["BACK_UPPER_BACK", "FRONT_BICEPS"],
            "secondaryMuscleGroups": ["BACK_DELTOIDS", "BACK_TRAPEZIUS"],
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "requiresLoadCalibration": False,
            "exerciseCategory": "MODERATE_COMPOUND"
        }
    ]
}

EXERCISE_SYSTEM_PROMPT = (
    "You must output JSON only. The output must be valid json. "
    "Do not include markdown or extra text.\n\n"
    "Generate ONLY the exercise list. Use placeholder IDs:\n"
    "- Exercise IDs: EXERCISE_0, EXERCISE_1, EXERCISE_2, etc.\n"
    "- Set IDs: SET_0, SET_1, SET_2, etc. (within each exercise)\n"
    "- Equipment references: Use the EQUIPMENT_X placeholders from the equipment list provided.\n"
    "Do NOT use real UUIDs - use placeholder IDs only.\n\n"
    "EQUIPMENT ENFORCEMENT:\n"
    "If available equipment is provided in the user message, you MUST:\n"
    "- Use only equipment from the provided list (reference their exact placeholder IDs)\n"
    "- Do not reference equipment IDs that are not in the provided list\n"
    "- Ensure equipmentId values match equipment from the provided list (or null for bodyweight)\n"
    "- Ensure requiredAccessoryEquipmentIds values match accessory equipment from the provided list\n"
    "- For WEIGHT exercises, all WeightSet weights must be from the valid weight combinations shown\n"
    "- For BODY_WEIGHT exercises, all BodyWeightSet additionalWeight values must be from the valid weight combinations shown\n\n"
    "CRITICAL FIELD REQUIREMENTS:\n\n"
    "1. Exercise Type and Set Type Consistency:\n"
    "   - WEIGHT exercises: MUST use only WeightSet in the sets array (RestSet is allowed between sets)\n"
    "   - BODY_WEIGHT exercises: MUST use only BodyWeightSet in the sets array (RestSet is allowed between sets)\n"
    "   - COUNTUP exercises: MUST use only EnduranceSet in the sets array (RestSet is allowed between sets)\n"
    "   - COUNTDOWN exercises: MUST use only TimedDurationSet in the sets array (RestSet is allowed between sets)\n"
    "   - Mismatched types will cause incorrect behavior in the app\n\n"
    "2. Reps Range (minReps/maxReps):\n"
    "   - COUNTUP exercises: MUST set minReps=0 and maxReps=0 (reps are meaningless for time-based exercises)\n"
    "   - COUNTDOWN exercises: MUST set minReps=0 and maxReps=0 (reps are meaningless for time-based exercises)\n"
    "   - WEIGHT exercises: MUST set minReps and maxReps to appropriate values > 0 (e.g., 5-8 for strength, 8-12 for hypertrophy)\n"
    "   - BODY_WEIGHT exercises: MUST set minReps and maxReps to appropriate values > 0 (e.g., 8-15 for strength, 12-20 for endurance)\n\n"
    "3. Load Percent Range (minLoadPercent/maxLoadPercent) - CRITICAL FOR DOUBLE PROGRESSION:\n"
    "   - These are CORE REQUIREMENTS for double progression training - they define the target intensity zone\n"
    "   - Double progression works by: start at minReps with a weight in the load % range → progress to maxReps → increase weight (stay in range) → drop to minReps → repeat\n"
    "   - WEIGHT exercises: MUST set reasonable values based on training goal:\n"
    "     * Strength training (1-5 reps): typically 85-100%\n"
    "     * Hypertrophy (6-12 reps): typically 65-85%\n"
    "     * Endurance (12+ reps): typically 50-70%\n"
    "     * Power/Explosive: typically 70-90%\n"
    "   - BODY_WEIGHT exercises: Set based on difficulty level (e.g., 50-70% for easier variations, 70-100% for advanced)\n"
    "   - COUNTUP exercises: Can be 0.0 (not applicable for time-based exercises)\n"
    "   - COUNTDOWN exercises: Can be 0.0 (not applicable for time-based exercises)\n"
    "   - CRITICAL: DO NOT use 0.0 for both values on WEIGHT or BODY_WEIGHT exercises - these are essential for proper progression\n"
    "   - If enableProgression=true, these MUST be set correctly to define the intensity range for progression\n\n"
    "4. Muscle Groups:\n"
    "   - EVERY exercise MUST have at least one primary muscle group in the muscleGroups array\n"
    "   - Definitions: muscleGroups (primary) = main movers; secondaryMuscleGroups (secondary) = synergists/stabilizers\n"
    "   - Expected number of items (use as targets):\n"
    "     * Compound lower body (squat, deadlift, lunge, hip thrust, etc.): 2-3 in muscleGroups, 1-2 in secondaryMuscleGroups\n"
    "     * Compound upper push (bench, OHP, push-up, dip): 2-3 primary, 2+ secondary\n"
    "     * Compound upper pull (row, pull-up, lat pulldown): 2-3 primary, 2+ secondary\n"
    "     * Isolation (curl, lateral raise, triceps extension, calf raise): 1 primary, 0-1 secondary\n"
    "   - Reference (use ONLY these enum values): Lower body: FRONT_QUADRICEPS, BACK_GLUTEAL, BACK_HAMSTRING, BACK_LOWER_BACK, FRONT_CALVES, BACK_CALVES, FRONT_ADDUCTORS, BACK_ADDUCTORS. Push: FRONT_CHEST, FRONT_DELTOIDS, FRONT_TRICEPS. Pull: BACK_UPPER_BACK, BACK_TRAPEZIUS, BACK_DELTOIDS, FRONT_BICEPS, BACK_TRICEPS. Core: FRONT_ABS, FRONT_OBLIQUES. Other: FRONT_FOREARM, BACK_FOREARM, FRONT_NECK, BACK_NECK (use when exercise clearly targets them).\n"
    "   - Empty muscleGroups array will prevent the muscle info page from showing in the app\n"
    "   - CRITICAL: Use ONLY the exact enum values listed below (case-sensitive, no variations):\n"
    "     * FRONT_ABS, FRONT_ADDUCTORS, FRONT_ANKLES, FRONT_BICEPS, FRONT_CALVES\n"
    "     * FRONT_CHEST, FRONT_DELTOIDS, FRONT_FEET, FRONT_FOREARM, FRONT_HANDS\n"
    "     * FRONT_KNEES, FRONT_NECK, FRONT_OBLIQUES, FRONT_QUADRICEPS, FRONT_TIBIALIS\n"
    "     * FRONT_TRAPEZIUS, FRONT_TRICEPS\n"
    "     * BACK_ADDUCTORS, BACK_ANKLES, BACK_CALVES, BACK_DELTOIDS, BACK_FEET\n"
    "     * BACK_FOREARM, BACK_GLUTEAL, BACK_HAMSTRING, BACK_HANDS, BACK_LOWER_BACK\n"
    "     * BACK_NECK, BACK_TRAPEZIUS, BACK_TRICEPS, BACK_UPPER_BACK\n"
    "   - Do NOT use variations like \"CHEST\", \"QUADS\", \"GLUTES\" - use the exact enum values above\n\n"
    "5. Exercise Name Hygiene:\n"
    "   - The exercise 'name' must be movement-only and concise (e.g., \"Warm Up\", \"Back Squat\", \"Single-Arm Row\").\n"
    "   - Do NOT include equipment or accessory details in name (e.g., \"spin bike\", \"barbell\", \"bands\", \"TRX\", \"pull-up bar\").\n"
    "   - Do NOT include set prescription details in name (sets, reps, rest, load, tempo, duration/time like \"5:00\").\n"
    "   - Put equipment/accessory requirements in equipmentId/requiredAccessoryEquipmentIds, and set/time details in sets.\n"
    "   - Bad example: \"Warm-up (spin bike, 5:00)\". Good example: \"Warm Up\".\n\n"
    "6. Set Type Specific Fields:\n"
    "   - WeightSet: Requires reps (integer), weight (number), subCategory (string)\n"
    "   - BodyWeightSet: Requires reps (integer), additionalWeight (number), subCategory (string)\n"
    "   - TimedDurationSet (for COUNTDOWN exercises): Requires timeInMillis (integer, NOT timeInSeconds), autoStart (boolean), autoStop (boolean). Does NOT have subCategory.\n"
    "   - EnduranceSet (for COUNTUP exercises): Requires timeInMillis (integer, NOT timeInSeconds), autoStart (boolean), autoStop (boolean). Does NOT have subCategory.\n"
    "   - RestSet: Requires timeInSeconds (integer), subCategory (string, typically \"WorkSet\")\n"
    "   - CRITICAL: TimedDurationSet and EnduranceSet use timeInMillis (milliseconds), not timeInSeconds\n"
    "   - CRITICAL: TimedDurationSet and EnduranceSet do NOT have subCategory field\n"
    "   - CRITICAL: Set types must match exercise type (see requirement #1 above)\n\n"
    "7. Equipment Weight Combinations (CRITICAL):\n"
    "   - For WEIGHT exercises with equipment: ALL WeightSet weights MUST be valid combinations for that equipment\n"
    "   - For BODY_WEIGHT exercises with equipment: ALL BodyWeightSet additionalWeight values MUST be valid combinations for that equipment\n"
    "   - Calculate valid weight combinations from the equipment's available plates/weights before setting set weights or additionalWeight\n"
    "   - Equipment types and their weight calculation:\n"
    "     * BARBELL: Sum of plates (both sides) + barWeight. Plates must fit within sleeveLength (thickness constraint, both in mm)\n"
    "     * DUMBBELLS: Each dumbbell weight × 2 (pair), plus combinations with extra weights if available\n"
    "     * DUMBBELL: Each dumbbell weight, plus combinations with extra weights if available\n"
    "     * MACHINE: Each availableWeight, plus combinations with extra weights if available\n"
    "     * PLATELOADEDCABLE: Sum of plates, must fit within sleeveLength (thickness constraint, both in mm)\n"
    "     * WEIGHTVEST: Each availableWeight value\n"
    "   - Example: If barbell has plates [20kg, 15kg, 10kg] and barWeight=20kg, valid weights include: 20kg (bar only), 40kg (bar+10kg×2), 50kg (bar+15kg×2), 60kg (bar+20kg×2), 70kg (bar+20kg+15kg×2), etc.\n"
    "   - Invalid weights will cause validation errors. Always verify weights match equipment capabilities.\n\n"
    "8. RestSet Configuration (REST BETWEEN SETS WITHIN AN EXERCISE):\n"
    "   - RestSet is ONLY used inside the 'sets' array of an Exercise object\n"
    "   - RestSet represents rest periods BETWEEN consecutive sets of the SAME exercise\n"
    "   - RestSet structure: {type: \"RestSet\", id: UUID, timeInSeconds: integer, subCategory: \"WorkSet\"}\n"
    "   - RestSet subCategory MUST be \"WorkSet\" for rest between work sets (this is the standard case)\n"
    "   - RestSet timeInSeconds should be appropriate for the exercise type:\n"
    "     * Strength training: 60-180 seconds (longer rest for heavy compound movements)\n"
    "     * Hypertrophy training: 30-90 seconds (shorter rest for muscle growth focus)\n"
    "     * Endurance training: 30-60 seconds (minimal rest for conditioning)\n"
    "   - Placement example: [WeightSet, RestSet(90s), WeightSet, RestSet(90s), WeightSet] for 3 work sets.\n"
    "   - When the plan entry specifies numWorkSets (e.g. 2), emit exactly that many work sets: e.g. for 2 sets use [WeightSet, RestSet(Ns), WeightSet].\n"
    "   - DO NOT use RestSet for rest between different exercises (use Rest Component instead)\n\n"
    "WARM-UP (COUNTDOWN):\n"
    "   - When the plan entry is the warm-up (exerciseType COUNTDOWN, name like \"Warm Up\" or \"General Warm Up\"): emit a SINGLE set only.\n"
    "   - Set structure: { \"type\": \"TimedDurationSet\", \"id\": \"<SET_X>\", \"timeInMillis\": 300000, \"autoStart\": true, \"autoStop\": true } (5 minutes). Do not add RestSet.\n"
    "   - Set minReps=0, maxReps=0, doNotStoreHistory=true, showCountDownTimer=true, equipmentId=null, generateWarmUpSets=false.\n"
    "   - Use placeholder set id (e.g. SET_WARMUP or SET_0 for that exercise).\n\n"
    "9. Other Required Fields:\n"
    "   - enabled: true (unless exercise should be disabled)\n"
    "   - doNotStoreHistory: true only for warmup-only, cooldown/mobility, technique drills, tests, or when the user requests no logging\n"
    "     * Otherwise set doNotStoreHistory: false for normal working sets\n"
    "     * If true, set enableProgression: false, but still populate reps, load percents, and sets correctly\n"
    "   - notes: REQUIRED string (use \"\" if no notes). Keep notes brief and focused on essential cues only. MAXIMUM of 500 characters.\n"
    "   - generateWarmUpSets: true for compound movements with heavy weights, false for isolation/light work\n"
    "   - exerciseCategory: Set for every WEIGHT and BODY_WEIGHT exercise. Determines evidence-based warm-up volume (NSCA/ACSM).\n"
    "     * HEAVY_COMPOUND: High axial load, high CNS demand (squat, deadlift, bench press, overhead press, row variations). Warm-up: 2-3 sets, ≤9 total reps.\n"
    "     * MODERATE_COMPOUND: Lunges, split squats, hip thrusts, machine presses, pull-ups. Warm-up: 1-2 sets, 4-6 reps.\n"
    "     * ISOLATION: Curls, lateral raises, triceps extensions, calf raises. Warm-up: 0-1 sets, 2-4 reps (often none if later in session).\n"
    "     * Set exerciseCategory to the appropriate enum for each exercise; use null only for COUNTUP/COUNTDOWN (e.g. warm-up exercise).\n"
    "   - enableProgression: true if the exercise should track progression over time\n"
    "   - keepScreenOn: false (unless it's a timed exercise that needs constant visibility)\n"
    "   - showCountDownTimer: false (unless it's a timed exercise that needs countdown)\n"
    "   - equipmentId: Must reference a valid EQUIPMENT_X placeholder from the equipment list, or null for pure bodyweight\n"
    "   - requiresLoadCalibration: false (default) - Set to true ONLY when the user explicitly requests calibration sets for this exercise\n"
    "     * Calibration sets allow users to perform a test set before work sets to determine the appropriate working weight based on RIR (Reps in Reserve)\n"
    "     * When true: A calibration set is automatically inserted before the first work set\n"
    "     * The user selects a load, performs the set, rates their RIR, and the app adjusts all remaining work set weights accordingly\n"
    "     * Only applicable to WEIGHT exercises or BODY_WEIGHT exercises with equipment (equipmentId != null)\n"
    "     * NOT applicable to COUNTUP or COUNTDOWN exercises\n"
    "     * Use when: User wants to dynamically adjust working weights based on daily readiness/performance\n"
    "     * Use when: User explicitly mentions \"calibration\", \"RIR-based weight selection\", or similar concepts\n"
    "     * Default to false unless explicitly requested - most exercises don't need calibration sets\n\n"
    "10. Required Accessory Equipment (requiredAccessoryEquipmentIds) - CRITICAL FOR ACCESSORY-DEPENDENT EXERCISES:\n"
    "   - requiredAccessoryEquipmentIds is an array of ACCESSORY_X placeholder IDs that reference accessory equipment items\n"
    "   - Use this field when an exercise REQUIRES accessory equipment to be performed (e.g., resistance bands, suspension trainer, pull-up bar)\n"
    "   - Accessory equipment is different from weight-loaded equipment (EQUIPMENT_X):\n"
    "     * Accessory equipment: Non-weight items like resistance bands, suspension trainers, pull-up bars, exercise balls, etc.\n"
    "     * Weight-loaded equipment: Items with weight specifications like barbells, dumbbells, machines (use equipmentId instead)\n"
    "   - When to include requiredAccessoryEquipmentIds:\n"
    "     * Exercises that require resistance bands (e.g., \"Band Pull-Aparts\", \"Band Face Pulls\", \"Band-Assisted Pull-Ups\")\n"
    "     * Exercises that require a suspension trainer/TRX (e.g., \"TRX Rows\", \"TRX Push-Ups\", \"TRX Pike\")\n"
    "     * Exercises that require a pull-up bar (e.g., \"Pull-Ups\", \"Chin-Ups\", \"Hanging Leg Raises\")\n"
    "     * Exercises that require an exercise ball (e.g., \"Ball Crunches\", \"Ball Push-Ups\")\n"
    "     * Any exercise where the accessory equipment is necessary to perform the movement\n"
    "   - When NOT to include (leave as empty array []):\n"
    "     * Exercises using only weight-loaded equipment (those use equipmentId, not requiredAccessoryEquipmentIds)\n"
    "     * Pure bodyweight exercises that don't need any equipment\n"
    "     * Optional equipment that enhances but isn't required for the exercise\n"
    "   - Format: Array of ACCESSORY_X placeholder IDs (e.g., [\"ACCESSORY_0\"] or [\"ACCESSORY_0\", \"ACCESSORY_1\"])\n"
    "   - CRITICAL: Use ACCESSORY_X placeholders from the accessoryEquipments list in the PlanIndex, NOT EQUIPMENT_X placeholders\n"
    "   - CRITICAL: If no accessory equipment is required, use an empty array [] (do not use null or omit the field)\n"
    "   - Example: A \"Band-Resisted Push-Ups\" exercise would have equipmentId: null (bodyweight) and requiredAccessoryEquipmentIds: [\"ACCESSORY_0\"] where ACCESSORY_0 is \"Resistance Bands\"\n\n"
    "11. Body Weight Percentage (bodyWeightPercentage) - CRITICAL FOR BODY_WEIGHT EXERCISES:\n"
    "   - bodyWeightPercentage is a percentage (0-100) representing what portion of the user's body weight should be used for the exercise\n"
    "   - This field is REQUIRED for BODY_WEIGHT exercises to properly calculate the effective weight being lifted\n"
    "   - The app uses this to calculate relative body weight: bodyWeight × (bodyWeightPercentage / 100)\n"
    "   - Typical values:\n"
    "     * 100.0: Full body weight exercises (e.g., push-ups, pull-ups, dips, squats)\n"
    "     * 50-70.0: Assisted or reduced body weight exercises (e.g., assisted pull-ups, inverted rows at 45-60° angle)\n"
    "     * 50.0: Single-leg exercises (half body weight per leg, e.g., single-leg squats, Bulgarian split squats)\n"
    "     * 60-80.0: Partial body weight exercises (e.g., knee push-ups, incline push-ups)\n"
    "   - For WEIGHT exercises: Set to null (not applicable)\n"
    "   - For COUNTUP/COUNTDOWN exercises: Set to null (not applicable)\n"
    "   - CRITICAL: Always include bodyWeightPercentage for BODY_WEIGHT exercises - it's essential for accurate weight tracking and progression\n\n"
    "12. Unilateral Exercises (Single-Arm/Single-Leg):\n"
    "   - The intraSetRestInSeconds field is used to mark exercises performed on one side at a time\n"
    "   - When intraSetRestInSeconds > 0: The exercise is unilateral (performed on left side, then right side)\n"
    "   - The value represents rest time between sides (typically 30-120 seconds)\n"
    "   - The app automatically creates two instances of each set (left side, then right side) with rest between them\n"
    "   - Set to null or 0 for bilateral exercises (default for most exercises)\n"
    "   - Typical values: 30-60s for isolation movements, 60-120s for compound unilateral movements\n"
    "   - Common examples: single-arm dumbbell rows, single-leg squats, Bulgarian split squats, single-arm overhead press, single-leg Romanian deadlifts\n"
    "   - Use unilateral exercises when:\n"
    "     * The exercise name indicates single-arm or single-leg (e.g., \"Single-Arm Row\", \"Single-Leg Squat\")\n"
    "     * The user specifically requests unilateral work for muscle imbalances or unilateral strength\n"
    "     * The exercise naturally requires one side at a time (e.g., split squats, lunges performed one leg at a time)\n\n"
    "13. Advanced Optional Fields (ONLY when explicitly requested by the user):\n"
    "   - Heart-rate target zone:\n"
    "     * Use lowerBoundMaxHRPercent and upperBoundMaxHRPercent ONLY if the user explicitly asks for HR targets/zones\n"
    "     * Otherwise set both fields to null\n"
    "     * If set, both must be present and between 1 and 100 (lower < upper)\n"
    "     * Use standard zones unless a custom zone is requested:\n"
    "       - Zone 2: 60-70%, Zone 3: 70-80%, Zone 4: 80-90%, Zone 5: 90-100%\n"
    "   - Load jump settings for progression:\n"
    "     * Use loadJumpDefaultPct, loadJumpMaxPct, loadJumpOvercapUntil ONLY if the user explicitly asks to tune progression jumps\n"
    "     * Otherwise set all three fields to null (app defaults will be used)\n"
    "     * If set: loadJumpDefaultPct ~ 0.025 (2.5%), loadJumpMaxPct ~ 0.10 (10%, must be >= default and <= 0.25),\n"
    "       loadJumpOvercapUntil ~ 2 (0-5 allowed)\n\n"
    "Include sets within each exercise. Use RestSet between sets when appropriate.\n\n"
    "Output format:\n"
    f"{json.dumps(EXERCISE_EXAMPLE, indent=2)}\n\n"
    "Generate all exercises needed for the workout based on the conversation and equipment list."
)

# Workout structure schema
WORKOUT_STRUCTURE_EXAMPLE = {
    "workoutMetadata": {
        "name": "Example Workout",
        "description": "Example description",
        "order": 0,
        "enabled": True,
        "usePolarDevice": False,
        "creationDate": "2026-01-06",
        "isActive": True,
        "timesCompletedInAWeek": None,
        "type": 0
    },
    "workoutComponents": [
        {
            "componentType": "Exercise",
            "exerciseId": "EXERCISE_WARMUP",
            "enabled": True
        },
        {
            "componentType": "Exercise",
            "exerciseId": "EXERCISE_0",
            "enabled": True
        },
        {
            "componentType": "Rest",
            "enabled": True,
            "timeInSeconds": 180
        },
        {
            "componentType": "Superset",
            "enabled": True,
            "exerciseIds": ["EXERCISE_1", "EXERCISE_2"],
            "restSecondsByExercise": {
                "EXERCISE_1": 60,
                "EXERCISE_2": 60
            }
        }
    ]
}

WORKOUT_STRUCTURE_SYSTEM_PROMPT = (
    "You must output JSON only. The output must be valid json. "
    "Do not include markdown or extra text.\n\n"
    "Generate the workout structure. Use placeholder IDs:\n"
    "- Component IDs: COMPONENT_0, COMPONENT_1, etc. (for Rest components and Supersets)\n"
    "- Exercise references: Use EXERCISE_X placeholders from the exercise list provided.\n"
    "- Workout ID: WORKOUT_0, WORKOUT_1, etc.\n"
    "- Global ID: WORKOUT_0_GLOBAL (will be converted to UUID)\n"
    "Do NOT use real UUIDs - use placeholder IDs only.\n\n"
    "WORKOUT METADATA ORDER:\n"
    "- workoutMetadata.order is a 0-based integer used to sort workouts in the app\n"
    "- Set order sequentially (0, 1, 2...) matching the workout list order\n"
    "- For a single workout, use order = 0\n"
    "- Keep order values unique unless user explicitly requests otherwise\n\n"
    "REST PERIODS - CRITICAL DISTINCTION:\n"
    "There are TWO different types of rest periods with DIFFERENT locations and purposes:\n\n"
    "1. RestSet (REST BETWEEN SETS WITHIN AN EXERCISE):\n"
    "   - Location: Inside the 'sets' array of an Exercise object\n"
    "   - Structure: {type: \"RestSet\", id: UUID, timeInSeconds: integer, subCategory: \"WorkSet\"}\n"
    "   - Purpose: Rest period between consecutive sets of the SAME exercise\n"
    "   - Example sequence: WeightSet → RestSet(90s) → WeightSet → RestSet(90s) → WeightSet\n"
    "   - Typical duration: 30-180 seconds (varies by training goal)\n"
    "   - Already included in exercise definitions - DO NOT add RestSet here\n\n"
    "2. Rest Component (REST BETWEEN DIFFERENT EXERCISES):\n"
    "   - Location: In the 'workoutComponents' array (at workout level, not inside exercises)\n"
    "   - Structure: {type: \"Rest\", id: UUID, enabled: boolean, timeInSeconds: integer}\n"
    "   - Purpose: Rest period between different exercises in the workout sequence\n"
    "   - Example sequence: Exercise A → Rest(180s) → Exercise B → Rest(180s) → Exercise C\n"
    "   - Add Rest components between Exercise components in workoutComponents array\n\n"
    "   REST DURATION DECISION RULES (CRITICAL - Apply consistently):\n"
    "   Determine rest timeInSeconds based on the PREVIOUS exercise (the one just completed):\n\n"
    "   A. Training Goal-Based Defaults:\n"
    "      - Strength training (1-5 reps, 85-100% load): 180 seconds (3 minutes)\n"
    "      - Hypertrophy training (6-12 reps, 65-85% load): 120 seconds (2 minutes)\n"
    "      - Endurance training (12+ reps, 50-70% load): 90 seconds (1.5 minutes)\n\n"
    "   B. Exercise Type Adjustments:\n"
    "      - Compound movements (squats, deadlifts, bench press, rows, overhead press):\n"
    "        * Add 30-60 seconds to the base duration\n"
    "        * Strength compound: 180-240s, Hypertrophy compound: 120-180s, Endurance compound: 90-120s\n"
    "      - Isolation movements (curls, tricep extensions, lateral raises, leg curls):\n"
    "        * Use base duration or subtract 30 seconds\n"
    "        * Strength isolation: 120-180s, Hypertrophy isolation: 90-120s, Endurance isolation: 60-90s\n\n"
    "   C. Muscle Group Overlap Adjustments:\n"
    "      - If next exercise targets SAME primary muscle group: Add 30-60 seconds\n"
    "      - If next exercise targets DIFFERENT muscle groups: Use base duration\n"
    "      - If next exercise is antagonist pair (e.g., biceps after triceps): Subtract 30 seconds\n\n"
    "   D. Final Duration Guidelines:\n"
    "      - Minimum: 60 seconds (only for low-intensity isolation exercises)\n"
    "      - Maximum: 240 seconds (only for very heavy compound strength exercises)\n"
    "      - Most common: 120-180 seconds (hypertrophy/strength compound movements)\n"
    "      - Keep rest periods CONSISTENT within the same workout unless there's a clear reason to vary\n"
    "      - If unsure, use 120 seconds as a safe default for most exercises\n\n"
    "   E. Consistency Rules:\n"
    "      - Use the SAME rest duration for similar exercise types in the same workout\n"
    "      - Only vary rest if exercises clearly differ in intensity or muscle group overlap\n"
    "      - Example: All compound strength exercises → 180s, all isolation hypertrophy → 120s\n\n"
    "   F. User-Specified Rest (OVERRIDES defaults):\n"
    "      - When the plan entry provides restToNextSeconds (array in same order as exerciseIds), use those values EXACTLY for each Rest component.\n"
    "      - Do NOT apply the training goal defaults (180s, 120s, 90s) when user-specified rest is provided.\n"
    "      - After the last exercise the value is 0: do NOT add a Rest component after the last exercise.\n\n"
    "CRITICAL RULES:\n"
    "   - RestSet belongs ONLY in exercise.sets array (rest within one exercise)\n"
    "   - Rest Component belongs ONLY in workoutComponents array (rest between exercises)\n"
    "   - NEVER mix them: RestSet ≠ Rest Component\n"
    "   - When generating workoutComponents, use Rest Component (not RestSet) for rest between exercises\n\n"
    "WARM-UP EXERCISE REQUIREMENT:\n"
    "   - ALWAYS include a warm-up exercise as the FIRST component in the workoutComponents array\n"
    "   - The first component must be an Exercise component whose exerciseId is the warm-up id from the exercise list (e.g. EXERCISE_WARMUP).\n"
    "   - The warm-up exercise must be a COUNTDOWN exercise type with a single TimedDurationSet of 5 minutes (300000 milliseconds)\n"
    "   - The warm-up exercise should have:\n"
    "     * exerciseType: \"COUNTDOWN\"\n"
    "     * A single set in the sets array: {type: \"TimedDurationSet\", timeInMillis: 300000, autoStart: true, autoStop: true}\n"
    "     * doNotStoreHistory: true (warm-up exercises should not be logged)\n"
    "     * showCountDownTimer: true (to display the countdown)\n"
    "     * Appropriate name (e.g., \"Warm Up\", \"General Warm Up\", \"Dynamic Warm Up\")\n"
    "   - This warm-up requirement applies UNLESS the user explicitly specifies a different warm-up duration, format, or requests no warm-up\n"
    "   - If the user requests a different warm-up (e.g., \"10 minute warm-up\" or \"no warm-up\"), follow their specification instead\n"
    "   - CRITICAL: NO Rest component should be added immediately after the warm-up exercise\n"
    "   - The warm-up exercise should be followed directly by the first work exercise (no rest period between warm-up and first exercise)\n\n"
    "CRITICAL: The workoutComponents array must contain ONLY valid component objects.\n"
    "- Each element must be a complete Exercise, Rest, or Superset component object\n"
    "- NEVER include null, undefined, or empty values in the workoutComponents array\n"
    "- If an exercise reference is missing, skip that component entirely rather than including null\n"
    "- The workoutComponents array defines the order of components in the workout\n"
    "For Exercise components, reference exercises by their EXERCISE_X placeholder.\n"
    "For Rest components, include timeInSeconds.\n"
    "For Superset components, include exerciseIds array and restSecondsByExercise mapping.\n"
    "Superset components must have at least one valid exercise - do not create empty supersets.\n\n"
    "Workout Metadata Fields:\n"
    "- The 'order' field in workoutMetadata determines the display/sorting order of workouts in the app\n"
    "- Lower numbers appear first when workouts are sorted\n"
    "- For a single workout, use order: 0\n"
    "- For multiple workouts, use sequential numbers (0, 1, 2, ...) based on the desired display order\n"
    "- The order should typically match the workout ID index (WORKOUT_0 should have order: 0, WORKOUT_1 should have order: 1, etc.)\n"
    "- The 'description' field should be short and concise, providing a brief overview of the workout's purpose or focus\n"
    "- CRITICAL: The 'description' field has a MAXIMUM of 50 characters - keep it within this limit\n"
    "- IMPORTANT: Make descriptions SPECIFIC to the actual exercises in the workout, not generic\n"
    "- Base the description on the exercises provided - reference key muscle groups, primary exercises, or training focus visible in the workout\n"
    "- Examples of good descriptions: 'Upper push/pull focus', 'Legs: quads & glutes', 'Chest & triceps', 'Back & biceps', 'Full body compound'\n"
    "- Avoid generic descriptions like 'Full body strength' or 'Hypertrophy workout' - be specific about what's actually in the workout\n"
    "- Keep descriptions to 1 sentence maximum, focusing on key characteristics visible in the exercise list\n"
    "- Avoid lengthy explanations or detailed instructions in the description field\n\n"
    "Output format:\n"
    f"{json.dumps(WORKOUT_STRUCTURE_EXAMPLE, indent=2)}\n\n"
    "Generate workout structure based on the conversation and exercise list."
)

# PlanIndex structure for planner/emitter architecture
PLAN_INDEX_EXAMPLE = {
    "equipments": [
        {
            "id": "EQUIPMENT_0",
            "type": "BARBELL",
            "name": "Standard Barbell"
        },
        {
            "id": "EQUIPMENT_1",
            "type": "DUMBBELLS",
            "name": "Standard Dumbbells",
            "maxExtraWeightsPerLoadingPoint": 0,
            "extraWeights": [],
            "dumbbells": [
                {"weight": 10.0},
                {"weight": 15.0},
                {"weight": 20.0}
            ]
        }
    ],
    "accessoryEquipments": [
        {
            "id": "ACCESSORY_0",
            "type": "ACCESSORY",
            "name": "Resistance Bands"
        }
    ],
    "exercises": [
        {
            "id": "EXERCISE_WARMUP",
            "equipmentId": None,
            "exerciseType": "COUNTDOWN",
            "name": "Warm Up",
            "muscleGroups": ["FRONT_QUADRICEPS"]
        },
        {
            "id": "EXERCISE_0",
            "equipmentId": "EQUIPMENT_0",
            "exerciseType": "WEIGHT",
            "name": "Back Squat",
            "muscleGroups": ["BACK_GLUTEAL", "FRONT_QUADRICEPS"],
            "exerciseCategory": "HEAVY_COMPOUND",
            "numWorkSets": 2,
            "minReps": 6,
            "maxReps": 10,
            "restBetweenSetsSeconds": 120
        },
        {
            "id": "EXERCISE_1",
            "equipmentId": "EQUIPMENT_0",
            "exerciseType": "WEIGHT",
            "name": "Bench Press",
            "muscleGroups": ["FRONT_CHEST", "FRONT_DELTOIDS", "FRONT_TRICEPS"],
            "requiredAccessoryEquipmentIds": [],
            "exerciseCategory": "HEAVY_COMPOUND"
        },
        {
            "id": "EXERCISE_2",
            "equipmentId": None,
            "exerciseType": "BODY_WEIGHT",
            "name": "Band Pull-Aparts",
            "muscleGroups": ["BACK_DELTOIDS"],
            "requiredAccessoryEquipmentIds": ["ACCESSORY_0"],
            "exerciseCategory": "ISOLATION"
        }
    ],
    "workouts": [
        {
            "id": "WORKOUT_0",
            "name": "Example Workout",
            "exerciseIds": ["EXERCISE_WARMUP", "EXERCISE_0", "EXERCISE_1", "EXERCISE_2"],
            "hasSupersets": False,
            "hasRestComponents": True,
            "restToNextSeconds": [0, 90, 90, 60]
        }
    ]
}

PLAN_INDEX_SYSTEM_PROMPT = (
    "You must output JSON only. The output must be valid json. "
    "Do not include markdown or extra text.\n\n"
    "You are generating a PlanIndex - a compact plan that defines what objects will exist, "
    "their placeholder IDs, and their relationships. This is NOT the full workout JSON.\n\n"
    "CRITICAL: Use ONLY placeholder IDs. Do NOT use real UUIDs.\n"
    "- Weight-loaded Equipment IDs: EQUIPMENT_0, EQUIPMENT_1, EQUIPMENT_2, etc.\n"
    "- Accessory Equipment IDs: ACCESSORY_0, ACCESSORY_1, ACCESSORY_2, etc.\n"
    "- Exercise IDs: EXERCISE_0, EXERCISE_1, EXERCISE_2, etc.\n"
    "- Workout IDs: WORKOUT_0, WORKOUT_1, etc.\n\n"
    "EQUIPMENT ENFORCEMENT:\n"
    "If available equipment is provided in the user message, you MUST:\n"
    "- Use equipment from the provided list (use their exact placeholder IDs) when available\n"
    "- CRITICAL: Equipment from the provided file is IMMUTABLE - you CANNOT edit, modify, or change any equipment from the provided list\n"
    "- When an exercise requires an accessory (e.g. pull-up bar, resistance bands), you MUST use the exact placeholder ID from the provided list if that accessory is already listed (same name). Do NOT create a new accessory with a new ID when the same accessory name already exists.\n"
    "- If necessary equipment is missing from the provided list, you MAY create new equipment entries with new placeholder IDs\n"
    "- When creating new equipment:\n"
    "  * Use new placeholder IDs (EQUIPMENT_X, ACCESSORY_X) that don't conflict with provided equipment IDs\n"
    "  * Collect all required details following the equipment detail collection guide from the conversation\n"
    "  * Include the new equipment in the equipments or accessoryEquipments arrays in the PlanIndex\n"
    "- Ensure all equipmentId and requiredAccessoryEquipmentIds values match equipment from either the provided list OR newly created equipment\n"
    "- Do not reference equipment IDs that don't exist in either the provided list or newly created equipment\n\n"
    "The PlanIndex should include:\n"
    "1. equipments: List of weight-loaded equipment entries with id (placeholder), type (BARBELL, MACHINE, etc.), and name\n"
    "2. accessoryEquipments: List of accessory equipment entries with id (placeholder ACCESSORY_X), type (ACCESSORY), and name\n"
    "3. exercises: List of exercise entries with id (placeholder), equipmentId (placeholder reference for weight-loaded equipment or null for bodyweight), "
    "exerciseType (WEIGHT, BODY_WEIGHT, COUNTUP, COUNTDOWN), name, primary muscleGroups, and optionally requiredAccessoryEquipmentIds (array of ACCESSORY_X placeholders).\n"
    "   - name: Use a clean movement name only. Keep essential movement/form qualifiers, but remove equipment/accessory details and set/time details from the name.\n"
    "     * Do NOT include equipment/accessory in name (e.g. \"spin bike\", \"barbell\", \"bands\", \"TRX\", \"pull-up bar\").\n"
    "     * Do NOT include set prescription in name (sets, reps, rest, load, tempo, duration/time like \"5:00\").\n"
    "     * Bad example: \"Warm-up (spin bike, 5:00)\". Good example: \"Warm Up\".\n"
    "   - equipmentId: References EQUIPMENT_X for weight-loaded equipment (barbells, dumbbells, machines, etc.) or null for bodyweight exercises\n"
    "   - requiredAccessoryEquipmentIds: Array of ACCESSORY_X placeholder IDs for accessory equipment that is REQUIRED to perform the exercise.\n"
    "     * Include this when the exercise needs accessory equipment like resistance bands, suspension trainers, pull-up bars, exercise balls, etc.\n"
    "     * Use empty array [] if no accessory equipment is required (most exercises)\n"
    "     * Examples: Pull-ups need pull-up bar → [\"ACCESSORY_0\"], Band pull-aparts need bands → [\"ACCESSORY_1\"], TRX rows need suspension trainer → [\"ACCESSORY_2\"]\n"
    "     * CRITICAL: Use ACCESSORY_X placeholders from the accessoryEquipments list, NOT EQUIPMENT_X placeholders\n\n"
    "4. workouts: List of workout entries with id (placeholder), name, exerciseIds (array of EXERCISE_X placeholders), "
    "hasSupersets (boolean), hasRestComponents (boolean). "
    "When the user provides a table with \"Rest to next exercise (s)\", add restToNextSeconds: array of integers in the SAME order as exerciseIds (rest after each exercise in seconds; use 0 after warm-up and 0 after the last exercise).\n\n"
    "OPTIONAL EXERCISE FIELDS (when user provides sets×reps and rest in a table):\n"
    "   - numWorkSets: integer (e.g. 2 for \"2×6–10\"). Omit for warm-up.\n"
    "   - minReps, maxReps: integers for rep range (e.g. 6 and 10 for \"6–10\"). Omit for COUNTDOWN/COUNTUP.\n"
    "   - restBetweenSetsSeconds: integer (rest between sets within this exercise). Omit for warm-up.\n\n"
    "WARM-UP:\n"
    "   - Include one warm-up exercise in exercises with exerciseType \"COUNTDOWN\", name e.g. \"Warm Up\" or \"General Warm Up\", "
    "equipmentId null, and one muscle group (e.g. a single value) so the schema is satisfied. Use a dedicated id, e.g. EXERCISE_WARMUP.\n"
    "   - For every workout, the exerciseIds array must list this warm-up id FIRST, then the work exercises, "
    "unless the user explicitly asks for no warm-up or a different warm-up.\n\n"
    "MUSCLE GROUPS:\n"
    "muscleGroups in the plan = all primary movers. For compound exercises, list 2-3 muscle groups (e.g. Back Squat -> FRONT_QUADRICEPS, BACK_GLUTEAL; Bench Press -> FRONT_CHEST, FRONT_DELTOIDS, FRONT_TRICEPS). For isolation exercises, one is enough. Do not list only one primary for compound movements.\n\n"
    "For exercises, muscleGroups must use ONLY these enum values (case-sensitive, no variations):\n"
    "FRONT_ABS, FRONT_ADDUCTORS, FRONT_ANKLES, FRONT_BICEPS, FRONT_CALVES, FRONT_CHEST, FRONT_DELTOIDS, FRONT_FEET, FRONT_FOREARM, FRONT_HANDS, FRONT_KNEES, FRONT_NECK, FRONT_OBLIQUES, FRONT_QUADRICEPS, FRONT_TIBIALIS, FRONT_TRAPEZIUS, FRONT_TRICEPS, "
    "BACK_ADDUCTORS, BACK_ANKLES, BACK_CALVES, BACK_DELTOIDS, BACK_FEET, BACK_FOREARM, BACK_GLUTEAL, BACK_HAMSTRING, BACK_HANDS, BACK_LOWER_BACK, BACK_NECK, BACK_TRAPEZIUS, BACK_TRICEPS, BACK_UPPER_BACK.\n"
    "Do NOT use BACK_LATISSIMUS (use BACK_UPPER_BACK), BACK_HAMSTRINGS (use BACK_HAMSTRING), CORE_ABDOMINALS (use FRONT_ABS), FRONT_SHOULDER (use FRONT_DELTOIDS), or any other variant.\n\n"
    "When the user provides a table or list with columns like \"Sets × reps\", \"Rest between sets (s)\", and \"Rest to next exercise (s)\", extract and include the optional exercise fields (numWorkSets, minReps, maxReps, restBetweenSetsSeconds) and workout field restToNextSeconds so the generated workout matches the user's specification exactly.\n\n"
    "Output format:\n"
    f"{json.dumps(PLAN_INDEX_EXAMPLE, indent=2)}\n\n"
    "Generate the PlanIndex based on the conversation context."
)

# JSON Patch repair system prompt
JSON_PATCH_REPAIR_SYSTEM_PROMPT = (
    "You are a JSON schema validation error fixer using JSON Patch (RFC 6902).\n\n"
    "CRITICAL INSTRUCTIONS:\n"
    "1. You will receive a JSON document with validation errors and a list of error messages\n"
    "2. You must output a JSON Patch array (RFC 6902) that fixes ONLY the validation errors\n"
    "3. Do NOT introduce new UUIDs - the document uses placeholder IDs (EQUIPMENT_X, EXERCISE_X, etc.)\n"
    "4. Do NOT modify fields that are already valid - only fix the specific errors mentioned\n"
    "5. Preserve all placeholder IDs and relationships\n"
    "6. Use contextually appropriate values when fixing errors (e.g., infer muscle groups from exercise names)\n"
    "7. NEVER set values to null in workoutComponents arrays - if a component is invalid, use \"remove\" operation instead\n"
    "8. When fixing workoutComponents, ensure each element is a complete, valid component object (Exercise, Rest, or Superset)\n"
    "9. If a component cannot be fixed, remove it rather than setting it to null\n\n"
    "EQUIPMENT ARRAY FORMAT REQUIREMENTS:\n"
    "All equipment arrays must contain objects, NOT numbers:\n"
    "- BARBELL/PLATELOADEDCABLE: availablePlates must be array of objects with {weight: number, thickness: number}\n"
    "  Example: [{\"weight\": 20.0, \"thickness\": 30.0}, {\"weight\": 15.0, \"thickness\": 25.0}]\n"
    "- DUMBBELLS/DUMBBELL: dumbbells and extraWeights must be arrays of objects with {weight: number}\n"
    "  Example: [{\"weight\": 10.0}, {\"weight\": 15.0}, {\"weight\": 20.0}]\n"
    "- WEIGHTVEST/MACHINE: availableWeights and extraWeights must be arrays of objects with {weight: number}\n"
    "  Example: [{\"weight\": 5.0}, {\"weight\": 10.0}, {\"weight\": 15.0}]\n"
    "If you see arrays with numbers like [1.0, 2.0, 3.0], convert them to objects: [{\"weight\": 1.0}, {\"weight\": 2.0}, {\"weight\": 3.0}]\n"
    "For plates missing thickness, add a default thickness of 20.0 (mm).\n\n"
    "JSON PATCH FORMAT:\n"
    "Output an array of patch operations, each with:\n"
    "- op: The operation (\"add\", \"remove\", \"replace\", \"move\", \"copy\")\n"
    "- path: JSON Pointer to the field (e.g., \"/workouts/0/workoutComponents/2/muscleGroups/0\")\n"
    "- value: The new value (for \"add\" and \"replace\") - NEVER use null for workoutComponents items\n\n"
    "EXAMPLE:\n"
    "If error says 'muscleGroups array is empty' for exercise at /workouts/0/workoutComponents/0:\n"
    "[{\"op\": \"add\", \"path\": \"/workouts/0/workoutComponents/0/muscleGroups\", \"value\": [\"FRONT_QUADRICEPS\", \"BACK_GLUTEAL\"]}]\n"
    "For compound exercises, use 2+ primary groups (e.g. bench -> [\"FRONT_CHEST\", \"FRONT_DELTOIDS\", \"FRONT_TRICEPS\"]).\n\n"
    "If error says 'availableWeights[0] is not of type object' for equipment at /equipments/2:\n"
    "[{\"op\": \"replace\", \"path\": \"/equipments/2/availableWeights\", \"value\": [{\"weight\": 1.0}, {\"weight\": 2.0}, {\"weight\": 3.0}]}]\n\n"
    "If error says 'None is not valid' for workoutComponents item at /workouts/0/workoutComponents/10:\n"
    "[{\"op\": \"remove\", \"path\": \"/workouts/0/workoutComponents/10\"}]\n\n"
    "OUTPUT REQUIREMENTS:\n"
    "You must output JSON only - a JSON Patch array. Do not include markdown, explanations, or extra text.\n"
    "Return only the JSON Patch array that fixes the validation errors."
)

# Function tool schema for OpenAI function calling
GENERATE_WORKOUT_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_workout",
        "description": "Generate a workout JSON file based on the conversation context. Use this when the user explicitly asks you to generate a workout or create workout JSON.",
        "parameters": {
            "type": "object",
            "properties": {
                "custom_prompt": {
                    "type": "string",
                    "description": "Optional additional instructions or requirements for the workout generation"
                }
            }
        }
    }
}
MUSCLE_GROUP_FIXES = {
    "BACK_QUADRICEPS": "FRONT_QUADRICEPS",
    "BACK_LATISSIMUS": "BACK_UPPER_BACK",
    "BACK_HAMSTRINGS": "BACK_HAMSTRING",
    "CORE_ABDOMINALS": "FRONT_ABS",
    "FRONT_SHOULDER": "FRONT_DELTOIDS",
    "CORE_OBLIQUE": "FRONT_OBLIQUES",
    "CHEST_PECTORAL": "FRONT_CHEST",
    "SHOULDER_ANTERIOR": "FRONT_DELTOIDS",
    "SHOULDER_LATERAL": "FRONT_DELTOIDS",
    "SHOULDER_POSTERIOR": "BACK_DELTOIDS",
    "ARM_TRICEPS": "FRONT_TRICEPS",
    "ARM_BICEPS": "FRONT_BICEPS",
    "BACK_RHOMBOID": "BACK_UPPER_BACK",
    "LATISSIMUS": "BACK_UPPER_BACK",
    "RHOMBOIDS": "BACK_UPPER_BACK",
    "PECTORALS": "FRONT_CHEST",
    "OBLIQUES": "FRONT_OBLIQUES",
    # Common variations
    "CHEST": "FRONT_CHEST",
    "QUADS": "FRONT_QUADRICEPS",
    "QUADRICEPS": "FRONT_QUADRICEPS",
    "HAMSTRINGS": "BACK_HAMSTRING",
    "HAMSTRING": "BACK_HAMSTRING",
    "GLUTES": "BACK_GLUTEAL",
    "GLUTEAL": "BACK_GLUTEAL",
    "GLUTE": "BACK_GLUTEAL",
    "BICEPS": "FRONT_BICEPS",
    "TRICEPS": "FRONT_TRICEPS",
    "SHOULDERS": "FRONT_DELTOIDS",
    "DELTS": "FRONT_DELTOIDS",
    "DELTOIDS": "FRONT_DELTOIDS",
    "ABS": "FRONT_ABS",
    "ABDOMINALS": "FRONT_ABS",
    "ABDOMINAL": "FRONT_ABS",
    "LATS": "BACK_UPPER_BACK",
    "TRAPS": "FRONT_TRAPEZIUS",
    "TRAPEZIUS": "FRONT_TRAPEZIUS",
    "CALVES": "FRONT_CALVES",
    "CALF": "FRONT_CALVES",
    "FOREARMS": "FRONT_FOREARM",
    "FOREARM": "FRONT_FOREARM",
    # Additional common typos/variations
    "QUAD": "FRONT_QUADRICEPS",
    "PECS": "FRONT_CHEST",
    "PEC": "FRONT_CHEST",
    "LOWER_BACK": "BACK_LOWER_BACK",
    "UPPER_BACK": "BACK_UPPER_BACK",
    "NECK": "FRONT_NECK",
}
