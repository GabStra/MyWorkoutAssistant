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

EXERCISE_TYPE_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["ExerciseType"]["enum"])
EXERCISE_CATEGORY_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["ExerciseCategory"]["enum"])
MUSCLE_GROUP_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["MuscleGroup"]["enum"])
SET_SUBCATEGORY_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["SetSubCategory"]["enum"])
WORKOUT_COMPONENT_TYPE_VALUES = "Exercise, Rest, Superset"

BASE_SYSTEM_PROMPT = (
    "You are a workout assistant. In normal chat mode, respond conversationally. "
    "When JSON generation is requested, follow JSON-mode system prompts.\n\n"
    "CONVERSATION RULES:\n"
    "1. Detect completeness first.\n"
    "- If the user already provided a structured plan (exercise names + sets/reps + rest, often as table/day split) and asks to generate, do not ask extra discovery questions.\n"
    "- Ask clarifying questions only when essential inputs are missing.\n\n"
    "2. Equipment handling.\n"
    "- Ask about equipment only when it is not already provided.\n"
    "- If provided equipment file exists, it is immutable: never edit/remove existing items.\n"
    "- You may add missing equipment/accessories with new placeholders (EQUIPMENT_X / ACCESSORY_X).\n"
    "- Before adding weight-loaded equipment, collect required technical details.\n"
    "- If user does not know values, propose defaults and ask for confirmation.\n\n"
    "3. Recommendation quality.\n"
    "- Recommend only exercises supported by available equipment.\n"
    "- Offer feasible alternatives when required equipment is unavailable.\n"
    "- Mark unilateral intent when exercise or user request indicates single-side work.\n\n"
    "4. Preview formatting.\n"
    "- For conversational preview workouts, use a clear plain-text table.\n"
    "- Keep notes concise and practical.\n\n"
    "5. Function usage.\n"
    "- Call generate_workout only when the user explicitly asks to generate/create workout JSON.\n"
    "- Optionally pass custom_prompt with extra constraints."
)

SUMMARIZATION_SYSTEM_PROMPT = (
    "Condense conversation history into only workout-generation-relevant facts.\n\n"
    "Include only:\n"
    "- goals, target muscles, constraints, style, duration/intensity preferences\n"
    "- available equipment (with any technical details)\n"
    "- include/exclude exercises\n"
    "- explicit prescriptions (sets, rep ranges, rest between sets, rest to next exercise)\n\n"
    "Rules:\n"
    "- Remove fluff and duplicates.\n"
    "- Preserve exercise names verbatim.\n"
    "- Preserve numeric values exactly (do not broaden ranges or replace user values).\n"
    "- If information is missing/unclear, mark it explicitly without guessing."
)

JSON_SYSTEM_PROMPT = (
    "Output JSON only (no markdown/explanations). Use valid UUIDs and ISO dates (YYYY-MM-DD).\n"
    "Use only equipment IDs that exist in equipments. Do not use IRONNECK.\n\n"
    "Numeric fidelity:\n"
    "- Preserve explicit user-provided numeric values exactly.\n\n"
    "Rest semantics (strict):\n"
    "- RestSet is only inside exercise.sets (between sets of the same exercise).\n"
    "- Rest component {type:\"Rest\"} is only in workoutComponents (between exercises).\n"
    "- Never mix RestSet and Rest component locations.\n"
    "- If user gives explicit rest values, use them exactly.\n"
    "- If not provided, pick consistent defaults by goal/intensity (strength usually longer than hypertrophy/endurance).\n\n"
    "Exercise validity:\n"
    "- WEIGHT -> WeightSet work sets; BODY_WEIGHT -> BodyWeightSet; COUNTUP -> EnduranceSet; COUNTDOWN -> TimedDurationSet.\n"
    "- COUNTUP/COUNTDOWN must use minReps=0 and maxReps=0.\n"
    "- WEIGHT/BODY_WEIGHT must have minReps/maxReps > 0 and valid load percent ranges.\n"
    f"- muscleGroups must be non-empty and use MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    f"- exerciseType must use ExerciseType enum values only: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- exerciseCategory must use ExerciseCategory enum values only: {EXERCISE_CATEGORY_ENUM_VALUES}.\n\n"
    "Text fields:\n"
    "- workout.description max 50 chars, concise and specific.\n"
    "- exercise.notes max 500 chars, concise.\n\n"
    "Optional advanced fields:\n"
    "- HR target fields and load jump tuning fields should be set only when explicitly requested; otherwise null.\n"
    "- If doNotStoreHistory=true, set enableProgression=false.\n\n"
    "JSON Schema:\n"
    f"{json.dumps(JSON_SCHEMA, indent=2)}\n\n"
    "Example JSON Output:\n"
    f"{json.dumps(EXAMPLE_JSON, indent=2)}"
)

SELF_HEAL_SYSTEM_PROMPT = (
    "Fix JSON schema validation errors with minimal, context-aware changes.\n\n"
    "Core rules:\n"
    "- Fix only failing fields; keep valid data unchanged.\n"
    "- Preserve IDs and relationships.\n"
    "- Use valid enum values and schema-compatible types.\n"
    f"- ExerciseType enum: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- ExerciseCategory enum: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    f"- MuscleGroup enum: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    f"- SetSubCategory enum: {SET_SUBCATEGORY_ENUM_VALUES}.\n"
    "- Prefer semantically correct fixes (infer from exercise/workout context).\n\n"
    "Input modes:\n"
    "- Full mode: complete WorkoutStore JSON -> return complete corrected JSON.\n"
    "- Targeted mode: {item, itemType, context} -> return only fixed item (no wrapper).\n\n"
    "Heuristics:\n"
    "- Empty/invalid muscle groups: infer from exercise name and type.\n"
    "- Missing equipmentId: null for bodyweight, otherwise map to available equipment in context.\n"
    "- Invalid exerciseType: infer from set types.\n"
    "- Invalid load/weight values: adjust to valid ranges/combinations from equipment context.\n"
    "- Adjust advanced optional fields only when already present.\n\n"
    "Output JSON only (no markdown/explanations)."
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
    "Output JSON only (no markdown/explanations).\n"
    "Generate only the equipment list using placeholder IDs (EQUIPMENT_X, ACCESSORY_X).\n"
    "Do not use real UUIDs. Do not use IRONNECK.\n\n"
    "Allowed types (exact): BARBELL, DUMBBELLS, DUMBBELL, PLATELOADEDCABLE, WEIGHTVEST, MACHINE, ACCESSORY.\n"
    "Required structures:\n"
    "- BARBELL/PLATELOADEDCABLE availablePlates: array of {weight, thickness} objects.\n"
    "- DUMBBELLS/DUMBBELL extraWeights and dumbbells: array of {weight} objects.\n"
    "- WEIGHTVEST availableWeights: array of {weight} objects.\n"
    "- MACHINE availableWeights and extraWeights: array of {weight} objects.\n"
    "- ACCESSORY: id, type, name only.\n"
    "Never output numeric arrays for weight lists.\n\n"
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
    "Output JSON only (no markdown/explanations).\n"
    "Generate only the exercise list with placeholder IDs (EXERCISE_X, SET_X). Do not use UUIDs.\n"
    "Use only provided equipment/accessory placeholder IDs.\n\n"
    "Output completeness (required):\n"
    "- Never leave required fields empty or invalid.\n"
    "- Do not output empty muscleGroups; if uncertain, infer best primary movers from exercise name.\n"
    "- Do not output invalid load ranges; for WEIGHT/BODY_WEIGHT ensure minLoadPercent < maxLoadPercent.\n"
    "- If user input is ambiguous/noisy, infer sensible schema-valid values rather than leaving blanks.\n\n"
    "Core constraints:\n"
    "- Name normalization: exercise name must be movement-only (no equipment/accessory words and no set/time details).\n"
    "- Remove equipment/accessory wording from names, e.g.:\n"
    "  * 'Barbell Back Squat' -> 'Back Squat'\n"
    "  * 'DB Bulgarian Split Squat' -> 'Bulgarian Split Squat'\n"
    "  * 'Cable Triceps Pushdown' -> 'Triceps Pushdown'\n"
    "  * '1-Arm DB Row (bench-supported)' -> '1-Arm Row'\n"
    "  * 'Warm up (spin bike)' -> 'Warm Up'\n"
    "- Type/set consistency: WEIGHT->WeightSet, BODY_WEIGHT->BodyWeightSet, COUNTUP->EnduranceSet, COUNTDOWN->TimedDurationSet. RestSet allowed only between sets.\n"
    f"- Valid ExerciseType enum values: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- Valid ExerciseCategory enum values: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    f"- Valid SetSubCategory enum values: {SET_SUBCATEGORY_ENUM_VALUES}.\n"
    "- TimedDurationSet/EnduranceSet use timeInMillis and do not include subCategory.\n"
    "- COUNTUP/COUNTDOWN use minReps=0,maxReps=0. WEIGHT/BODY_WEIGHT use positive rep ranges.\n"
    "- WEIGHT/BODY_WEIGHT require valid minLoadPercent/maxLoadPercent (not both zero).\n"
    f"- muscleGroups must be non-empty and use valid MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    "- requiredAccessoryEquipmentIds must use ACCESSORY_X placeholders (use [] when none).\n"
    "- BODY_WEIGHT exercises must include bodyWeightPercentage; WEIGHT/COUNTUP/COUNTDOWN set it to null.\n"
    "- Set weights/additionalWeight must be valid for equipment combinations.\n\n"
    "Warm-up rule:\n"
    "- For COUNTDOWN warm-up entry, emit exactly one TimedDurationSet of 300000 ms, no RestSet, doNotStoreHistory=true, showCountDownTimer=true, equipmentId=null.\n\n"
    "Other required behavior:\n"
    "- Use notes as concise string (max 500 chars).\n"
    "- Set exerciseCategory for WEIGHT/BODY_WEIGHT (HEAVY_COMPOUND, MODERATE_COMPOUND, ISOLATION); null for COUNTUP/COUNTDOWN.\n"
    "- requiresLoadCalibration=true only when user explicitly requests calibration; otherwise false.\n"
    "- Optional HR/load-jump fields only when explicitly requested; otherwise null.\n\n"
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
    "Output JSON only (no markdown/explanations).\n"
    "Generate one workout structure using placeholder IDs (WORKOUT_X, COMPONENT_X, EXERCISE_X).\n\n"
    "Structure rules:\n"
    "- Return workoutMetadata + workoutComponents only.\n"
    "- workoutMetadata.order is 0-based and follows workout order.\n"
    "- workoutMetadata.description must be specific and <= 50 chars.\n"
    f"- workoutComponents may contain only valid componentType values: {WORKOUT_COMPONENT_TYPE_VALUES}.\n"
    "- Never output null/empty components.\n\n"
    "Rest rules:\n"
    "- RestSet is internal to exercise.sets and must not be created here.\n"
    "- Rest component is between exercises in workoutComponents.\n"
    "- If restToNextSeconds is provided, use values exactly.\n"
    "- If a transition rest value is 0, do not add a Rest component.\n"
    "- Never place a Rest component immediately after the warm-up.\n\n"
    "Warm-up rules:\n"
    "- First component must be warm-up exercise reference (EXERCISE_WARMUP) unless user asked otherwise.\n"
    "- Warm-up is expected as COUNTDOWN with single TimedDurationSet 300000ms in exercise definitions.\n\n"
    "Superset rules:\n"
    "- Include exerciseIds and restSecondsByExercise mapping.\n"
    "- Superset must include at least one valid exercise.\n\n"
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
            "restToNextSeconds": [0, 90, 90, 0]
        }
    ]
}

PLAN_INDEX_SYSTEM_PROMPT = (
    "Output JSON only (no markdown/explanations).\n"
    "Generate a PlanIndex (not full workout JSON) using placeholder IDs only.\n"
    "IDs: EQUIPMENT_X, ACCESSORY_X, EXERCISE_X, WORKOUT_X.\n\n"
    "Equipment constraints:\n"
    "- Provided equipment/accessory lists are immutable.\n"
    "- Reuse existing IDs when available (especially accessories by same name).\n"
    "- Create new items only when missing, with non-conflicting placeholders.\n"
    "- Ensure all equipmentId/requiredAccessoryEquipmentIds references exist.\n\n"
    "Exercise constraints:\n"
    "- Exercise names must be movement-only labels (remove equipment/accessory wording and set/time details).\n"
    "- Examples: 'Barbell Back Squat' -> 'Back Squat', 'Cable Triceps Pushdown' -> 'Triceps Pushdown', 'Warm up (spin bike)' -> 'Warm Up'.\n"
    f"- exerciseType must use one of: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- exerciseCategory (when present) must use one of: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    "- For accessory-dependent exercises, use requiredAccessoryEquipmentIds with ACCESSORY_X IDs; use [] when none.\n"
    f"- Use valid MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    "- If user provided sets/reps/rest table, copy values exactly into optional fields (numWorkSets, minReps, maxReps, restBetweenSetsSeconds).\n\n"
    "Workout constraints:\n"
    "- Preserve exact workout names from user plan (including day labels/prefixes such as 'A -', 'Day A:', etc.).\n"
    "- workout.exerciseIds defines exact order.\n"
    "- If provided, restToNextSeconds must match exerciseIds length and values exactly.\n"
    "- Include warm-up as first exercise ID (EXERCISE_WARMUP) unless user explicitly requests otherwise.\n\n"
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
    "ENUM CONSTRAINTS (use exact values):\n"
    f"- ExerciseType: {EXERCISE_TYPE_ENUM_VALUES}\n"
    f"- ExerciseCategory: {EXERCISE_CATEGORY_ENUM_VALUES}\n"
    f"- MuscleGroup: {MUSCLE_GROUP_ENUM_VALUES}\n"
    f"- SetSubCategory: {SET_SUBCATEGORY_ENUM_VALUES}\n"
    f"- workoutComponents.componentType: {WORKOUT_COMPONENT_TYPE_VALUES}\n\n"
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
    "Output JSON only (no markdown/explanations) as a JSON Patch array.\n"
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

