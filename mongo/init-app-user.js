const required = ["MONGO_DB_NAME", "MONGO_APP_USERNAME", "MONGO_APP_PASSWORD"];
for (const name of required) {
  if (!process.env[name]) {
    throw new Error(`Missing required initialization setting: ${name}`);
  }
}

const applicationDatabase = db.getSiblingDB(process.env.MONGO_DB_NAME);
applicationDatabase.createUser({
  user: process.env.MONGO_APP_USERNAME,
  pwd: process.env.MONGO_APP_PASSWORD,
  roles: [{ role: "readWrite", db: process.env.MONGO_DB_NAME }],
});
