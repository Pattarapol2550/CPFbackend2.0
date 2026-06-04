MONGO_DETAILS = "mongodb://localhost:27017"

client = AsyncIOMotorClient(MONGO_DETAILS)

database = client.thermoCPF

metrics_collection = database.get_collection(
    "compressor_data_v2"
)